"""Transporte Cloud API. Sin GPS, reintentos implícitos ni logs de peticiones."""
import logging
import requests

from .config import normalize_number

logger = logging.getLogger(__name__)
TEXT_LIMIT = 4096


class WhatsAppError(RuntimeError):
    def __init__(self, category, status=None):
        self.category, self.status = category, status
        super().__init__(f"Fallo de WhatsApp: {category}.")


class WhatsAppClient:
    def __init__(self, config, *, post=None):
        self.config = config
        self.post = post or requests.post
        self.endpoint = f"https://graph.facebook.com/{config.api_version}/{config.phone_number_id}/messages"

    def _send(self, recipient, content):
        payload = {"messaging_product": "whatsapp", "recipient_type": "individual",
                   "to": normalize_number(recipient), **content}
        failure = None
        try:
            response = self.post(self.endpoint, json=payload,
                                 headers={"Authorization": "Bearer " + self.config.access_token},
                                 timeout=(5, 20), allow_redirects=False)
            with response:
                status = response.status_code
                if status in (401, 403):
                    failure = WhatsAppError("authentication", status)
                elif not 200 <= status < 300:
                    failure = WhatsAppError("http", status)
                else:
                    data = response.json()
                    messages = data.get("messages") if isinstance(data, dict) else None
                    if (not isinstance(messages, list) or not messages
                            or not isinstance(messages[0], dict)
                            or not isinstance(messages[0].get("id"), str) or not messages[0]["id"]
                            or data.get("error")):
                        failure = WhatsAppError("unexpected_response")
                    else:
                        message_id = messages[0]["id"]
        except requests.exceptions.JSONDecodeError:
            failure = WhatsAppError("unexpected_response")
        except requests.Timeout:
            failure = WhatsAppError("timeout")
        except requests.ConnectionError:
            failure = WhatsAppError("connection")
        except requests.RequestException:
            failure = WhatsAppError("transport")
        except (ValueError, TypeError, KeyError):
            failure = WhatsAppError("unexpected_response")
        # Fuera del except: no conservar requests autenticados en __context__.
        if failure:
            logger.warning("Envío WhatsApp fallido: categoría=%s, HTTP=%s.", failure.category, failure.status)
            raise failure
        logger.info("Mensaje WhatsApp aceptado por Meta; entrega no confirmada.")
        return message_id

    def send_text(self, recipient, text):
        if not isinstance(text, str) or not text.strip() or len(text) > TEXT_LIMIT:
            raise WhatsAppError("configuration")
        return self._send(recipient, {"type": "text", "text": {"body": text, "preview_url": False}})

    def send_template(self, recipient, name, language, parameters):
        if not name or not language or any(not isinstance(p, str) or not p for p in parameters):
            raise WhatsAppError("configuration")
        template = {"name": name, "language": {"code": language}}
        if parameters:
            template["components"] = [{"type": "body", "parameters": [
                {"type": "text", "text": value} for value in parameters]}]
        return self._send(recipient, {"type": "template", "template": template})
