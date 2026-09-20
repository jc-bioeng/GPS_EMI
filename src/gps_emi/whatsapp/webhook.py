"""GET de verificación y POST firmado. Solo valida y encola, nunca consulta GPS."""
from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
import math

from flask import Flask, request, Response

logger = logging.getLogger(__name__)
MAX_BODY_BYTES = 1024 * 1024


@dataclass(frozen=True, repr=False)
class IncomingMessage:
    message_id: str
    sender: str
    text: str
    timestamp: float


def valid_signature(body, signature, secret):
    if not isinstance(signature, str) or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode("ascii"), signature.encode("utf-8"))


def _objects(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def extract_messages(payload, phone_number_id):
    if payload.get("object") != "whatsapp_business_account":
        return []
    result = []
    for entry in _objects(payload.get("entry")):
        for change in _objects(entry.get("changes")):
            value = change.get("value")
            if change.get("field") != "messages" or not isinstance(value, dict):
                continue
            metadata = value.get("metadata")
            if not isinstance(metadata, dict) or metadata.get("phone_number_id") != phone_number_id:
                continue
            for message in _objects(value.get("messages")):
                text = message.get("text")
                if message.get("type") != "text" or not isinstance(text, dict):
                    continue
                body, sender, identifier = text.get("body"), message.get("from"), message.get("id")
                if (not all(isinstance(s, str) and s for s in (body, sender, identifier))
                        or len(body) > 4096 or len(sender) > 64 or len(identifier) > 512):
                    continue
                try:
                    timestamp = float(message.get("timestamp"))
                except (ValueError, TypeError, OverflowError):
                    continue
                if math.isfinite(timestamp) and timestamp > 0:
                    result.append(IncomingMessage(identifier, sender, body, timestamp))
    return result


def create_app(config, inbox):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES

    @app.get("/webhook")
    def verify():
        supplied = request.args.get("hub.verify_token", "")
        if (request.args.get("hub.mode") != "subscribe"
                or not hmac.compare_digest(supplied.encode(), config.verify_token.encode())
                or not request.args.get("hub.challenge")):
            return Response("Forbidden", status=403)
        logger.info("Webhook verificado.")
        return Response(request.args["hub.challenge"], status=200, mimetype="text/plain")

    @app.post("/webhook")
    def receive():
        body = request.get_data()
        if not valid_signature(body, request.headers.get("X-Hub-Signature-256"), config.app_secret):
            logger.warning("Webhook rechazado por firma ausente o inválida.")
            return Response("Forbidden", status=403)
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            return Response("Invalid payload", status=400)
        if not isinstance(payload, dict):
            return Response("Invalid payload", status=400)
        messages = extract_messages(payload, config.phone_number_id)
        if not inbox.submit(messages):
            return Response("Busy", status=503, headers={"Retry-After": "5"})
        return Response("OK", status=200)

    @app.errorhandler(Exception)
    def safe_error(error):
        from werkzeug.exceptions import HTTPException
        code = error.code if isinstance(error, HTTPException) else 500
        logger.warning("Petición webhook rechazada: HTTP %s.", code)
        return Response("Request rejected", status=code)

    return app
