"""Orquestación de una vigilancia; nunca convierte fallos en observaciones."""
from datetime import datetime
import logging
import time
from typing import Protocol

from gps_emi.config import WatchConfig
from gps_emi.errors import AcquisitionError, TransientAcquisitionError
from gps_emi.models import Vehicle
from gps_emi.monitoring.arrival import ArrivalMonitor, DESTINATIONS
from gps_emi.monitoring.observation import (
    ObservationValidator, ObservationStatus, observe_resolved_vehicle,
)
from gps_emi.notifications.base import NotificationService
from gps_emi.resolution import (
    find_vehicle, find_vehicle_by_id, VehicleResolutionError,
    VehicleNotFoundError, AmbiguousVehicleError,
)

logger = logging.getLogger(__name__)


class VehicleSource(Protocol):
    def get_vehicles(self) -> list[Vehicle]: ...


def local_now():
    # WideTech entrega fechas sin offset. Se comparan con el reloj local del host.
    return datetime.now()


class WatchRunner:
    def __init__(self, client: VehicleSource, identifier: str, destination: str,
                 notifier: NotificationService, config: WatchConfig | None = None,
                 *, sleep=None, now=None):
        if not identifier.strip():
            raise ValueError("Introduzca una placa o número de móvil.")
        if destination not in DESTINATIONS:
            raise ValueError("Destino no permitido.")
        self.client = client
        self.identifier = identifier.strip()
        self.destination = destination
        self.notifier = notifier
        self.config = config or WatchConfig()
        self.sleep = sleep if sleep is not None else time.sleep
        self.now = now if now is not None else local_now
        self.monitor: ArrivalMonitor | None = None
        self.vehid: str | None = None
        self.validator = ObservationValidator()
        self.consecutive_failures = 0
        self._next_backoff = self.config.initial_backoff
        self._diagnostic_timestamp = object()
        self._diagnostics: set[str] = set()
        self._result: int | None = None

    def _retry(self, message):
        self.consecutive_failures += 1
        delay = self._next_backoff
        self._next_backoff = min(self.config.max_backoff, delay * 2)
        logger.warning("%s Fallo consecutivo %d; reintentando en %g s.",
                       message, self.consecutive_failures, delay)
        self.sleep(delay)

    def _recovered(self):
        if self.consecutive_failures:
            logger.info("Adquisición recuperada después de %d fallos; polling normal restaurado.",
                        self.consecutive_failures)
        self.consecutive_failures = 0
        self._next_backoff = self.config.initial_backoff

    def _warn_once(self, code, message, *args):
        if code not in self._diagnostics:
            logger.warning(message, *args)
            self._diagnostics.add(code)

    def _process(self, vehicle):
        assessment = self.validator.evaluate(vehicle, self.now())
        timestamp = vehicle.gps_timestamp
        if timestamp != self._diagnostic_timestamp:
            self._diagnostic_timestamp = timestamp
            self._diagnostics.clear()
        age = assessment.report_age
        if age is not None and age > self.config.stale_warning_seconds:
            self._warn_once("STALE", "STALE: última posición reportada hace %.0f s (GPS=%s).", age, timestamp)
        if age is not None and age < 0:
            self._warn_once("FUTURE", "Fecha GPS posterior al reloj de consulta; revise los relojes (GPS=%s).", timestamp)
        if vehicle.gps_fix in (0, False, "0"):
            self._warn_once("GPSFix", "GPSFix=0: dato diagnóstico; no se descarta la observación.")
        if assessment.status == ObservationStatus.DUPLICATE:
            logger.debug("DUPLICATE: sin reporte GPS nuevo para VEHID=%s.", self.vehid)
            return False
        if assessment.status != ObservationStatus.NEW:
            self._warn_once(assessment.status.value,
                            "%s: observación no procesada (VEHID=%s, GPS=%s).",
                            assessment.status.value, self.vehid, timestamp)
            return False
        event = observe_resolved_vehicle(self.monitor, vehicle, expected_vehid=self.vehid)
        self.validator.last_processed_gps_timestamp = timestamp
        membership = "INSIDE" if self.destination in vehicle.zones else "OUTSIDE"
        logger.info("%s | última posición reportada: %s | report_age=%.0f s | GPSFix=%s",
                    membership, timestamp, age, vehicle.gps_fix)
        if event is None:
            return False
        logger.info("ARRIVAL_DETECTED: VEHID=%s, placa=%s, móvil=%s, destino=%s.",
                    vehicle.vehid, vehicle.plate, vehicle.mobile_number, self.destination)
        self.notifier.send_arrival(event)
        logger.info("Vigilancia completada.")
        return True

    def _run(self):
        logger.info("Vigilando %s → %s", self.identifier, self.destination)
        while True:
            try:
                vehicles = self.client.get_vehicles()
            except TransientAcquisitionError as error:
                self._retry(error.public_message)
                continue
            except AcquisitionError as error:
                logger.error("%s Vigilancia detenida.", error.public_message)
                return 1
            if self.vehid is None:
                try:
                    vehicle = find_vehicle(vehicles, self.identifier)
                    if not vehicle.vehid:
                        logger.error("El móvil resuelto no tiene VEHID; vigilancia detenida.")
                        return 1
                    vehicle = find_vehicle_by_id(vehicles, vehicle.vehid)
                except VehicleResolutionError as error:
                    logger.error("%s Vigilancia detenida.", error)
                    return 1
                self.vehid = vehicle.vehid
                self.monitor = ArrivalMonitor(vehicle.display_identifier, self.destination)
                logger.info("Identificador resuelto: VEHID=%s, placa=%s, móvil=%s.",
                            vehicle.vehid, vehicle.plate, vehicle.mobile_number)
            else:
                try:
                    vehicle = find_vehicle_by_id(vehicles, self.vehid)
                except VehicleNotFoundError:
                    self._retry("El VEHID vigilado está temporalmente ausente; estado conservado.")
                    continue
                except AmbiguousVehicleError:
                    logger.error("El VEHID vigilado es ambiguo; vigilancia detenida.")
                    return 1
            self._recovered()
            if self._process(vehicle):
                return 0
            self.sleep(self.config.polling_interval)

    def run(self) -> int:
        if self._result is not None:
            return self._result
        try:
            self._result = self._run()
        except (KeyboardInterrupt, EOFError):
            logger.info("Vigilancia cancelada.")
            self._result = 130
        except Exception:
            # Nunca volcar excepciones desconocidas, cuerpos ni peticiones. No se
            # reintenta una notificación fallida: podría haberse enviado ya.
            logger.error("Error no recuperable durante la vigilancia; operación detenida.")
            self._result = 1
        return self._result
