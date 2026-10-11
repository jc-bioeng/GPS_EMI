import logging

from gps_emi.models import ArrivalEvent

logger = logging.getLogger(__name__)


class ConsoleNotifier:
    def send_arrival(self, event: ArrivalEvent) -> None:
        if event.event_type == 'PRESENCE_CONFIRMED':
            logger.info("%s: presencia confirmada en %s tras interrupción. Hora del reporte GPS: %s. "
                        "No se conoce la hora de llegada; vigilancia finalizada.",
                        event.vehicle.display_identifier, event.destination, event.vehicle.gps_timestamp)
            return
        logger.info("%s llegó a %s | Hora GPS reportada: %s",
                    event.vehicle.display_identifier, event.destination,
                    event.vehicle.gps_timestamp or 'no disponible')
