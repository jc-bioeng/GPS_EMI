"""Orquestación de una vigilancia; nunca convierte fallos en observaciones."""
import logging
from threading import Event, RLock
from typing import Protocol

from gps_emi.config import WatchConfig
from gps_emi.acquisition import SnapshotSource, SnapshotUnavailable
from gps_emi.catalog import MEDELLIN_FLEETS
from gps_emi.clock import operational_now
from gps_emi.errors import AcquisitionError
from gps_emi.models import Vehicle
from gps_emi.sites import matching_sites
from gps_emi.monitoring.arrival import ArrivalMonitor, DESTINATIONS
from gps_emi.monitoring.continuity import Continuity
from gps_emi.monitoring.observation import (
    ObservationValidator, ObservationStatus, gps_fix_warning,
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
    return operational_now()


class _WatchEnded(Exception):
    pass


class WatchRunner:
    def __init__(self, client: SnapshotSource, identifier: str, destination: str | None,
                 notifier: NotificationService, config: WatchConfig | None = None,
                 *, sleep=None, now=None, on_resolved=None, stop_event=None, confirm_inside=None):
        if not identifier.strip():
            raise ValueError("Introduzca una placa o número de móvil.")
        if destination is not None and destination not in DESTINATIONS:
            raise ValueError("Destino no permitido.")
        self.client = client
        self.identifier = identifier.strip()
        self.destination = destination
        self.notifier = notifier
        self.config = config or WatchConfig()
        self.sleep = sleep  # Accepted for API compatibility; the runner never sleeps.
        self.now = now if now is not None else local_now
        self.on_resolved = on_resolved
        self.confirm_inside = confirm_inside
        self.stop_event = stop_event
        self.failure_code = None
        self.monitor: ArrivalMonitor | None = None
        self.vehid: str | None = None
        self.validator = ObservationValidator()
        self._diagnostic_timestamp = object()
        self._diagnostics: set[str] = set()
        self._result: int | None = None
        self._fleet_changed = Event()
        self._lock = RLock()
        self.continuity = None
        self._completed = False

    def _published(self, snapshot):
        with self._lock:
            if self._completed or self.failure_code is not None:
                return
            if snapshot is not None and self.vehid is not None and any(
                    item.vehicle_id == self.vehid and item.fleet_name and item.fleet_name not in MEDELLIN_FLEETS
                    for item in snapshot.identities):
                self._fleet_changed.set()

    def _tick(self):
        with self._lock:
            if self._completed:
                return
            if self.stop_event is not None and self.stop_event.is_set():
                raise KeyboardInterrupt()
            coordinator = self.client.coordinator
            if self._fleet_changed.is_set():
                self.failure_code = 'fleet_changed'
            elif coordinator.blocked or coordinator.closed:
                self.failure_code = 'acquisition'
            elif self.continuity is not None and self.continuity.tick(
                    coordinator.monotonic(), self.config, coordinator.watch_timing):
                self.failure_code = 'inactivity'
            if self.failure_code is not None:
                logger.info('Vigilancia terminada: reason=%s.', self.failure_code)
                raise _WatchEnded()

    def _warn_once(self, code, message, *args):
        if code not in self._diagnostics:
            logger.warning(message, *args)
            self._diagnostics.add(code)

    def _process(self, vehicle):
        with self._lock:
            if self._completed:
                return True
            self._tick()
            event = self._observe(vehicle)
            if event is None:
                return False
            self._completed = True  # Reserve the only attempt before releasing lock.
        self.notifier.send_arrival(event)
        logger.info("Vigilancia completada.")
        return True

    def _observe(self, vehicle):
        coordinator = self.client.coordinator
        if self.continuity is None:
            self.continuity = Continuity(coordinator.monotonic())
        previous_state = self.monitor.state
        assessment, event = self.continuity.observe(
            vehicle, coordinator.monotonic(), self.now(), self.config, coordinator.watch_timing,
            self.monitor, self.validator, self.vehid)
        timestamp = vehicle.gps_timestamp
        if timestamp != self._diagnostic_timestamp:
            self._diagnostic_timestamp = timestamp
            self._diagnostics.clear()
        age = assessment.report_age
        if assessment.is_stale(self.config.stale_warning_seconds):
            self._warn_once("STALE", "STALE: última posición reportada hace %.0f s (GPS=%s).", age, timestamp)
        if age is not None and age < 0:
            self._warn_once("FUTURE", "Fecha GPS posterior al reloj de consulta; revise los relojes (GPS=%s).", timestamp)
        if gps_fix_warning(vehicle.gps_fix):
            self._warn_once("GPSFix", "GPSFix=0: dato diagnóstico; no se descarta la observación.")
        if assessment.status == ObservationStatus.DUPLICATE:
            logger.debug("DUPLICATE: sin reporte GPS nuevo para VEHID=%s.", self.vehid)
            return None
        if assessment.status != ObservationStatus.NEW:
            self._warn_once(assessment.status.value,
                            "%s: observación no procesada (VEHID=%s, GPS=%s).",
                            assessment.status.value, self.vehid, timestamp)
            return None
        if assessment.is_stale(300):
            return None
        if self.destination is None:
            membership = "INSIDE_EMI" if self.monitor.actual_sites else "OUTSIDE_EMI"
        else:
            membership = "INSIDE" if self.destination in vehicle.zones else "OUTSIDE"
        log = logger.info if previous_state != self.monitor.state else logger.debug
        log("%s | última posición reportada: %s | report_age=%.0f s | GPSFix=%s",
                    membership, timestamp, age, vehicle.gps_fix)
        if event is None:
            return None
        logger.info("%s: VEHID=%s, placa=%s, móvil=%s, destino=%s.",
                    event.event_type, vehicle.vehid, vehicle.plate, vehicle.mobile_number, event.destination)
        return event

    def _run(self):
        logger.info("Vigilando %s → %s", self.identifier, self.destination or "EMI (Poblado o Taller)")
        version = None
        while True:
            if self.stop_event is not None and self.stop_event.is_set():
                return 130
            self._tick()
            try:
                snapshot = self.client.wait(after_version=version, stop_event=self.stop_event, on_tick=self._tick)
                version = (snapshot.epoch, snapshot.version)
                self._published(snapshot)
                if self._fleet_changed.is_set():
                    self.failure_code = 'fleet_changed'
                    logger.info('Vigilancia terminada: reason=fleet_changed.')
                    return 1
                vehicles = self.client.bind(snapshot).get_vehicles(include_retained=False, purpose='watch')
            except SnapshotUnavailable:
                self._tick()
                if self.vehid is not None:
                    continue
                self.failure_code = 'acquisition'
                return 1
            except AcquisitionError as error:
                self.failure_code = 'fleet_changed' if self._fleet_changed.is_set() else "acquisition"
                logger.error("%s Vigilancia detenida.", error.public_message)
                return 1
            if self.stop_event is not None and self.stop_event.is_set():
                return 130
            if self.vehid is None:
                try:
                    vehicle = find_vehicle(vehicles, self.identifier)
                    if not vehicle.vehid:
                        self.failure_code = "identity"
                        logger.error("El móvil resuelto no tiene VEHID; vigilancia detenida.")
                        return 1
                    vehicle = find_vehicle_by_id(vehicles, vehicle.vehid)
                except VehicleResolutionError as error:
                    self.failure_code = "not_found" if isinstance(error, VehicleNotFoundError) else "ambiguous"
                    logger.error("%s Vigilancia detenida.", error)
                    return 1
                require_exit = bool(matching_sites(vehicle.zones)) and self.confirm_inside is not None
                if require_exit:
                    offered_at = self.client.coordinator.monotonic()
                    if (not self.confirm_inside(vehicle) or
                            self.client.coordinator.monotonic() - offered_at >= 300):
                        self.failure_code = 'confirmation_cancelled'
                        logger.info('Vigilancia no iniciada: confirmación cancelada o vencida.')
                        return 0
                    # The user may take time to answer. Revalidate the same ID
                    # against the latest publication, without a separate HTTP call.
                    try:
                        vehicle = find_vehicle_by_id(self.client.bind(self.client.coordinator.peek()).get_vehicles(
                            include_retained=False, purpose='watch'), vehicle.vehid)
                    except VehicleResolutionError:
                        self.failure_code = 'selected_unavailable'
                        logger.info('Vigilancia no iniciada: identidad seleccionada no disponible.')
                        return 1
                self.vehid = vehicle.vehid
                self._published(self.client.coordinator.peek())
                if self._fleet_changed.is_set():
                    self.failure_code = 'fleet_changed'
                    return 1
                self.monitor = ArrivalMonitor(vehicle.display_identifier, self.destination)
                self.continuity = Continuity(self.client.coordinator.monotonic(), require_exit=require_exit)
                logger.info("Identificador resuelto: VEHID=%s, placa=%s, móvil=%s.",
                            vehicle.vehid, vehicle.plate, vehicle.mobile_number)
                if self.on_resolved is not None:
                    self.on_resolved(vehicle)
            else:
                try:
                    vehicle = find_vehicle_by_id(vehicles, self.vehid)
                except VehicleNotFoundError:
                    logger.warning("El VEHID vigilado está temporalmente ausente; estado conservado.")
                    continue
                except AmbiguousVehicleError:
                    self.failure_code = "ambiguous"
                    logger.error("El VEHID vigilado es ambiguo; vigilancia detenida.")
                    return 1
            if self._process(vehicle):
                return 0

    def run(self) -> int:
        if self._result is not None:
            return self._result
        self.client.coordinator.subscribers.append(self._published)
        try:
            self._result = self._run()
        except _WatchEnded:
            self._result = 1
        except (KeyboardInterrupt, EOFError):
            logger.info("Vigilancia cancelada.")
            self._result = 130
        except Exception:
            self.failure_code = "internal"
            # Nunca volcar excepciones desconocidas, cuerpos ni peticiones. No se
            # reintenta una notificación fallida: podría haberse enviado ya.
            logger.error("Error no recuperable durante la vigilancia; operación detenida.")
            self._result = 1
        finally:
            self.client.coordinator.subscribers.remove(self._published)
        return self._result


def watch_arrival(client: SnapshotSource, identifier: str, notifier: NotificationService,
                  config: WatchConfig | None = None, *, destination: str | None = None,
                  sleep=None, now=None, confirm_inside=None) -> int:
    """Caso de uso de vigilancia a EMI; destination es compatibilidad explícita I2."""
    return WatchRunner(client, identifier, destination, notifier, config,
                       sleep=sleep, now=now, confirm_inside=confirm_inside).run()
