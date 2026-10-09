"""Vigilancias en memoria, independientes del canal y del transporte GPS."""
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging
from threading import RLock
from uuid import uuid4

from gps_emi.config import WatchConfig
from gps_emi.models import Vehicle, ArrivalEvent
from .arrival import ArrivalMonitor
from .observation import ObservationAssessment, ObservationValidator, ObservationStatus, observe_resolved_vehicle, gps_fix_warning
from . import runner

logger = logging.getLogger(__name__)


class WatchStatus(str, Enum):
    ACTIVE = 'ACTIVE'
    COMPLETED = 'COMPLETED'
    CANCELLED = 'CANCELLED'
    FAILED = 'FAILED'  # Adquisición terminal o fallo local; nunca equivale a llegada.


@dataclass(repr=False)
class Watch:
    watch_id: str
    owner_id: str
    vehicle_id: str
    mobile_number: str
    plate: str
    created_at: datetime
    notification_target: str
    monitor: ArrivalMonitor
    status: WatchStatus = WatchStatus.ACTIVE
    validator: ObservationValidator = field(default_factory=ObservationValidator)
    last_observation: Vehicle | None = None
    last_assessment: ObservationAssessment | None = None
    event: ArrivalEvent | None = None
    notification_status: str = 'not_attempted'
    failure_code: str | None = None
    diagnostics: set = field(default_factory=set, repr=False)
    diagnostic_timestamp: object = field(default_factory=object, repr=False)


class WatchManager:
    """Serializa cambios; devuelve copias y ejecuta notificaciones fuera del lock.

    La transición a COMPLETED reserva atómicamente el único intento de envío.
    Cancelación anterior a esa transición gana; después, la llegada ya está tomada.
    """
    def __init__(self, notify, config=None, *, now=None):
        self.notify = notify
        self.config = config or WatchConfig()
        self.now = now or runner.local_now
        self._lock = RLock()
        self._watches = {}
        self.closed = False

    def create_watch(self, owner_id, vehicle, notification_target):
        if not owner_id or not notification_target or not vehicle.vehid:
            raise ValueError('Propietario, destino e identidad técnica requeridos.')
        with self._lock:
            if self.closed:
                raise RuntimeError('Gestión cerrada.')
            for watch in self._watches.values():
                if (watch.owner_id, watch.vehicle_id, watch.status) == (owner_id, vehicle.vehid, WatchStatus.ACTIVE):
                    return deepcopy(watch), False
            watch = Watch(uuid4().hex, owner_id, vehicle.vehid, vehicle.mobile_number,
                          vehicle.plate, self.now(), notification_target,
                          ArrivalMonitor(vehicle.display_identifier))
            self._watches[watch.watch_id] = watch
            logger.info('Watch creada watch_id=%s VEHID=%s.', watch.watch_id, watch.vehicle_id)
            return deepcopy(watch), True

    def get_watch(self, owner_id, watch_id):
        with self._lock:
            watch = self._watches.get(watch_id)
            return deepcopy(watch) if watch is not None and watch.owner_id == owner_id else None

    def list_watches(self, owner_id):
        with self._lock:
            return [deepcopy(w) for w in self._watches.values() if w.owner_id == owner_id]

    def get_active_watches(self, owner_id):
        return [w for w in self.list_watches(owner_id) if w.status == WatchStatus.ACTIVE]

    def has_active(self):
        with self._lock:
            return any(w.status == WatchStatus.ACTIVE for w in self._watches.values())

    def active_count(self):
        with self._lock:
            return sum(w.status == WatchStatus.ACTIVE for w in self._watches.values())

    def cancel_watch(self, owner_id, watch_id):
        with self._lock:
            watch = self._watches.get(watch_id)
            if watch is None or watch.owner_id != owner_id or watch.status != WatchStatus.ACTIVE:
                return None
            watch.status = WatchStatus.CANCELLED
            logger.info('Watch cancelada watch_id=%s VEHID=%s.', watch_id, watch.vehicle_id)
            return deepcopy(watch)

    def fail_active(self, code):
        with self._lock:
            failed = []
            for watch in self._watches.values():
                if watch.status == WatchStatus.ACTIVE:
                    watch.status, watch.failure_code = WatchStatus.FAILED, code
                    failed.append(deepcopy(watch))
                    logger.error('Watch failed watch_id=%s VEHID=%s reason=%s', watch.watch_id, watch.vehicle_id, code)
            return failed

    def close(self):
        with self._lock:
            self.closed = True
            for watch in self._watches.values():
                if watch.status == WatchStatus.ACTIVE:
                    watch.status = WatchStatus.CANCELLED

    def process_snapshot(self, vehicles, *, observed_at=None, watch_ids=None):
        now = observed_at if observed_at is not None else self.now()
        index = {}
        for vehicle in vehicles:
            index.setdefault(vehicle.vehid, []).append(vehicle)
        deliveries = []
        with self._lock:
            if self.closed:
                return []
            for watch in self._watches.values():
                if watch_ids is not None and watch.watch_id not in watch_ids:
                    continue
                if watch.status != WatchStatus.ACTIVE:
                    continue
                rows = index.get(watch.vehicle_id, [])
                if len(rows) != 1:
                    # Ausencia/identidad duplicada no demuestra salida de la geocerca.
                    code = 'missing_vehicle' if not rows else 'ambiguous_vehicle'
                    if code not in watch.diagnostics:
                        logger.warning('Observación omitida watch_id=%s motivo=%s.', watch.watch_id, code)
                        watch.diagnostics.add(code)
                    continue
                vehicle = rows[0]
                try:
                    assessment = watch.validator.evaluate(vehicle, now)
                    watch.last_observation = deepcopy(vehicle)
                    watch.last_assessment = assessment
                    if vehicle.gps_timestamp != watch.diagnostic_timestamp:
                        watch.diagnostics.clear()
                        watch.diagnostic_timestamp = vehicle.gps_timestamp
                    codes = []
                    if assessment.is_stale(self.config.stale_warning_seconds):
                        codes.append('STALE')
                    if gps_fix_warning(vehicle.gps_fix):
                        codes.append('GPSFix=0')
                    if assessment.report_age is not None and assessment.report_age < 0:
                        codes.append('FUTURE')
                    if assessment.status != ObservationStatus.NEW:
                        codes.append(assessment.status.value)
                    for code in codes:
                        if code not in watch.diagnostics:
                            log = logger.debug if code == 'DUPLICATE' else logger.warning
                            log('Diagnóstico watch_id=%s código=%s.', watch.watch_id, code)
                            watch.diagnostics.add(code)
                    if assessment.status != ObservationStatus.NEW:
                        logger.debug('watch observation ignored watch_id=%s reason=%s', watch.watch_id, assessment.status.value)
                        continue
                    previous = watch.monitor.state
                    event = observe_resolved_vehicle(watch.monitor, vehicle, watch.vehicle_id)
                    watch.validator.last_processed_gps_timestamp = vehicle.gps_timestamp
                    watch.mobile_number, watch.plate = vehicle.mobile_number, vehicle.plate
                    if previous != watch.monitor.state:
                        logger.info('Watch watch_id=%s VEHID=%s previous=%s estado=%s sites=%s.', watch.watch_id, watch.vehicle_id, previous.value, watch.monitor.state.value, watch.monitor.actual_sites)
                    if event is not None:
                        watch.event = deepcopy(event)
                        watch.status = WatchStatus.COMPLETED
                        watch.notification_status = 'attempting'
                        deliveries.append(deepcopy(watch))
                        logger.info('Llegada detectada; Watch completada watch_id=%s.', watch.watch_id)
                except Exception:
                    watch.status, watch.failure_code = WatchStatus.FAILED, 'observation'
                    logger.error('Observación fallida watch_id=%s; otras vigilancias continúan.', watch.watch_id)
        for watch in deliveries:
            logger.info('notification attempted watch_id=%s VEHID=%s', watch.watch_id, watch.vehicle_id)
            try:
                accepted = self.notify(watch, watch.event)
                outcome = 'accepted' if accepted is not False else 'failed'
            except Exception:
                outcome = 'failed'
                logger.error('Notificación fallida watch_id=%s; sin reintento automático.', watch.watch_id)
            with self._lock:
                self._watches[watch.watch_id].notification_status = outcome
            logger.log(logging.INFO if outcome == 'accepted' else logging.ERROR,
                       'notification result watch_id=%s outcome=%s', watch.watch_id, outcome)
        return deliveries
