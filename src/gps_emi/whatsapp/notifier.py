"""Adaptador de ArrivalEvent. Un fallo de entrega no reinicia el monitor."""
import logging

from .client import WhatsAppError
from .formatting import display, format_arrival

logger = logging.getLogger(__name__)


class WhatsAppNotifier:
    def __init__(self, recipient, messenger, config):
        self.recipient, self.messenger, self.config = recipient, messenger, config
        self.last_event = None
        self.delivery_error = None
        self.accepted = False

    def send_arrival(self, event):
        if self.last_event is not None:
            return
        self.last_event = event
        logger.info("Evento %s; preparando notificación WhatsApp.", event.event_type)
        try:
            if event.event_type == "PRESENCE_CONFIRMED" or self.config.arrival_mode == "text":
                self.messenger.reply(self.recipient, format_arrival(event))
            elif event.site is None:
                # No introducir una sede elegida arbitrariamente en la plantilla.
                raise WhatsAppError("ambiguous_arrival_site")
            else:
                self.messenger.client.send_template(
                    self.recipient, self.config.template_name, self.config.template_language,
                    [display(event.vehicle.mobile_number), display(event.vehicle.plate),
                     event.site, display(event.vehicle.gps_timestamp)],
                )
            self.accepted = True
        except WhatsAppError as error:
            self.delivery_error = error.category
            logger.error("Notificación de llegada pendiente de revisión manual: %s. Sin reintento automático.", error.category)
        except Exception:
            self.delivery_error = "internal"
            logger.error("Notificación de llegada fallida; evento conservado en memoria, sin detalles internos.")
