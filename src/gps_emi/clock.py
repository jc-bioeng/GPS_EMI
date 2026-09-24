"""Reloj operativo EMI; no depende de la zona horaria del host."""
from datetime import datetime
import logging
from zoneinfo import ZoneInfo

BOGOTA = ZoneInfo("America/Bogota")


def acquisition_now():
    """Instante inequívoco de adquisición, independiente del timezone del host."""
    return datetime.now(BOGOTA)


def operational_now():
    # Fecha de GPSpace se conserva naive, como hora de pared operativa EMI.
    # No se reinterpreta ni convierte el timestamp recibido del proveedor.
    return datetime.now(BOGOTA).replace(tzinfo=None)


class OperationalFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created, BOGOTA).isoformat(timespec="seconds")
