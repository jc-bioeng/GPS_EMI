import logging

from gps_emi.models import ArrivalEvent

logger = logging.getLogger(__name__)


class ConsoleNotifier:
    def send_arrival(self, event: ArrivalEvent) -> None:
        logger.info("%s llegó a %s | Hora GPS reportada: %s",
                    event.vehicle.display_identifier, event.destination,
                    event.vehicle.gps_timestamp or 'no disponible')
