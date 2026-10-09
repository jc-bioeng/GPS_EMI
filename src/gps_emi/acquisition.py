"""One scheduler owns acquisition; consumers only read immutable snapshots."""
from concurrent.futures import Future
from collections import Counter
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import math
import logging
from threading import Condition, Thread
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from gps_emi.errors import AcquisitionError, TransientAcquisitionError
from gps_emi.models import Vehicle, normalize_plate
from gps_emi.catalog import identities, Identity, CatalogView, MEDELLIN_FLEETS
from gps_emi.providers.widetech_official import AcquisitionResult, ErrorKind, OfficialAcquisitionError, OfficialRecord


class SnapshotUnavailable(TransientAcquisitionError):
    public_message = "Adquisición inicializando o temporalmente no disponible."


class CoordinatorClosed(AcquisitionError):
    public_message = "La autoridad de adquisición está detenida."


def _finish(future, snapshot=None, error=None):
    # Cancellation may race publication/expiry from the Inbox thread. Claim the
    # future atomically before completing it, without reviving cancelled work.
    if future.done() or not future.set_running_or_notify_cancel():
        return
    if error is not None:
        future.set_exception(error)
    else:
        future.set_result(snapshot)


@dataclass(frozen=True)
class AcquisitionConfig:
    interval: float = 30
    max_backoff: float = 300
    pending_timeout: float = 120
    capacity: int = 100

    def __post_init__(self):
        if (any(not math.isfinite(v) or v <= 0 for v in
                (self.interval, self.max_backoff, self.pending_timeout))
                or self.max_backoff < self.interval or type(self.capacity) is not int or self.capacity < 1):
            raise ValueError("Configuración de adquisición inválida.")


@dataclass(frozen=True, repr=False)
class RecordState:
    """Original observation and acquisition identity; never redate retained data."""
    record: OfficialRecord
    epoch: str
    version: int
    acquired_at: datetime
    retained_reason: str | None = None

    @property
    def source(self):
        return self.record.source


@dataclass(frozen=True, repr=False)
class Snapshot:
    epoch: str
    version: int
    acquired_at: datetime
    result: AcquisitionResult | None
    # Legacy deployment bridge only. Copies are never handed out directly.
    _legacy: tuple[Vehicle, ...] = ()
    operational: tuple[RecordState, ...] = ()
    identities: tuple[Identity, ...] = ()
    catalog: CatalogView | None = None

    @property
    def usable_records(self):
        return tuple(state.record for state in self.operational if state.retained_reason is None)

    @property
    def source(self):
        return self.result.source if self.result is not None else "LoadDataLog-explicit-legacy"

    @property
    def diagnostics(self):
        return self.result.diagnostics if self.result is not None else ()

    @property
    def records(self):
        return self.result.records if self.result is not None else tuple(replace(v, zones=list(v.zones)) for v in self._legacy)

    @property
    def coverage(self):
        return "unknown"


def _reconcile(batch, previous, epoch, version, acquired):
    # Whole-row retention avoids fabricating an observation from different reports.
    # The adapter's original rows and diagnostics remain untouched in result.
    states = {s.record.vehicle_id: replace(s, retained_reason='not_received')
              for s in previous.operational} if previous is not None else {}
    counts = Counter(r.vehicle_id for r in batch.records)
    diagnosed = {d.row for d in batch.diagnostics}
    for index, row in enumerate(batch.records, 1):
        identity = row.vehicle_id
        reason = None
        if not identity or counts[identity] > 1 or identity in batch.duplicate_ids:
            reason = 'ambiguous_identity'
        elif row.diagnostics or index in diagnosed:
            reason = 'row_quality'
        elif (row.gps_timestamp is None or row.latitude is None or row.longitude is None
              or not row.fleet_name or row.raw.get('Zones') is None):
            reason = 'incomplete_observation'
        if reason:
            if identity in states:
                states[identity] = replace(states[identity], retained_reason=reason)
        else:
            states[identity] = RecordState(row, epoch, version, acquired)
    return tuple(states.values())


class Coordinator:
    """tick is deterministic; only its guarded acquisition section calls the source.

    source.acquire() returns the phase-1 result, or a legacy tuple supplied by
    explicit composition. No fallback between sources exists.
    """
    def __init__(self, source, config=None, *, monotonic=time.monotonic,
                 utcnow=lambda: datetime.now(timezone.utc), lease=None, catalog=None, mapping=None):
        self.source, self.config = source, config or AcquisitionConfig()
        self.monotonic, self.utcnow, self.lease = monotonic, utcnow, lease
        self.catalog, self.mapping = catalog, mapping
        self.condition = Condition()
        self.epoch = uuid4().hex
        self._snapshot = self._received = None
        self.published_at = None
        self.next_start = monotonic()
        self.backoff = 0.0
        self.inflight = self.closed = self.blocked = False
        self.pending = []
        self.demands = set()
        self.probes = []
        self.subscribers = []
        self.thread = None
        self.state = "INITIALIZING"
        self.last_error = None
        self.metrics = dict(requests=0, successes=0, errors=0, rejected=0, duration=0.0)
        if lease is not None:
            self.next_start += lease.remaining(self.utcnow())

    def peek(self):
        with self.condition:
            return self._snapshot

    def received(self):
        with self.condition:
            return self._received

    def health(self):
        with self.condition:
            age = None if self._snapshot is None else max(0, (self.utcnow()-self._snapshot.acquired_at).total_seconds())
            snapshot = self._snapshot
            received = len(snapshot.records) if snapshot else 0
            usable = len(snapshot.usable_records) if snapshot and snapshot.result is not None else received
            retained = sum(s.retained_reason is not None for s in snapshot.operational) if snapshot else 0
            return {**self.metrics, "state": self.state, "snapshot_age": age,
                    "wait": max(0, self.next_start-self.monotonic()), "pending": len(self.pending),
                    "error": self.last_error, "received_rows": received,
                    "usable_rows": usable, "retained_records": retained}

    def demand(self, name, active):
        with self.condition:
            if active:
                self.demands.add(name)
            else:
                self.demands.discard(name)
            self.condition.notify_all()

    def request(self, *, refresh=False, after_version=None):
        future = Future()
        with self.condition:
            self._expire(self.monotonic())
            if self.closed:
                future.set_exception(CoordinatorClosed())
            elif self._snapshot is not None and (not refresh or (after_version is not None and
                    (self._snapshot.epoch, self._snapshot.version) != after_version)):
                future.set_result(self._snapshot)
                # A one-off query can use the last valid data, but an old cache
                # must not prevent all future acquisition in a query-only process.
                if (not self.blocked and not self.pending and self.published_at is not None and
                        self.monotonic()-self.published_at >= self.config.interval):
                    self.pending.append((Future(), self.monotonic()+self.config.pending_timeout))
                    self.condition.notify_all()
            elif self.blocked:
                future.set_exception(SnapshotUnavailable())
            elif len(self.pending) >= self.config.capacity:
                future.set_exception(SnapshotUnavailable())
            else:
                self.pending.append((future, self.monotonic()+self.config.pending_timeout))
                self.condition.notify_all()
        return future

    def _expire(self, now):
        keep = []
        for future, deadline in self.pending:
            if future.done():
                continue
            if now >= deadline:
                _finish(future, error=SnapshotUnavailable())
            else:
                keep.append((future, deadline))
        self.pending = keep

    def tick(self):
        # Probe callbacks are local demand checks, not HTTP or notification work.
        probe_demand = any(probe() for probe in self.probes)
        with self.condition:
            now = self.monotonic()
            self._expire(now)
            if (self.closed or self.blocked or self.inflight or now < self.next_start
                    or not (self.pending or self.demands or probe_demand)):
                return False
            self.inflight = True
            self.next_start = now + self.config.interval
            if self.lease is not None:
                try:
                    self.lease.reserve(self.utcnow(), self.config.interval)
                except Exception:
                    self.inflight = False
                    self.request_stop()
                    return False
            self.metrics["requests"] += 1
            now = self.monotonic()
            self.next_start = max(self.next_start, now+self.config.interval)
        result = None
        error = None
        retry = None
        try:
            result = self.source.acquire()
            if isinstance(result, AcquisitionResult):
                retry = result.retry_after
            elif not isinstance(result, tuple) or any(not isinstance(v, Vehicle) for v in result):
                raise OfficialAcquisitionError(ErrorKind.PAYLOAD)
        except OfficialAcquisitionError as failure:
            error = (failure.kind.value, failure.functional_code)
            retry = failure.retry_after
        except AcquisitionError as failure:
            error = ("legacy_transient" if isinstance(failure, TransientAcquisitionError) else "authentication", None)
        except Exception:
            error = ("internal", None)
        except BaseException:
            with self.condition:
                self.inflight = False
                self.request_stop()
            raise
        finished = self.monotonic()
        acquired = self.utcnow()
        with self.condition:
            self.metrics["duration"] = max(0, finished-now)
            retry_delay = 0
            if retry is not None:
                retry_delay = (retry.seconds if retry.seconds is not None else
                               max(0, (retry.at-acquired).total_seconds()))
            self.next_start = max(self.next_start, finished+retry_delay)
            if self.closed:
                self.inflight = False
                self._save_deadline(acquired, finished)
                if self.thread is None and self.lease is not None:
                    self.lease.close()
                self.condition.notify_all()
                return False
            self._expire(finished)
            if result is not None and error is None:
                version = 1 if self._received is None else self._received.version+1
                batch = result if isinstance(result, AcquisitionResult) else None
                self._received = Snapshot(self.epoch, version, acquired, batch,
                                          () if batch else tuple(replace(v, zones=tuple(v.zones)) for v in result),
                                          _reconcile(batch, self._snapshot, self.epoch, version, acquired) if batch else (),
                                          identities(batch, self.mapping) if batch else ())
                try:
                    if batch is not None and self.catalog is not None:
                        self._received = replace(self._received, catalog=self.catalog.apply(self._received))
                except Exception:
                    error = ('persistence', None)
                else:
                    self._snapshot = self._received
                    self.published_at = finished
            if error is not None:
                if self.catalog is not None:
                    self.catalog.interrupt()
                logging.getLogger(__name__).warning('Adquisición fallida: categoría=%s.', error[0])
                self.metrics["errors"] += 1
                self.last_error = error
                self.blocked = error[0] in ("authorization", "authentication", "configuration", "functional", "service_unavailable")
                self.state = "BLOCKED_METHOD" if self.blocked else "UNAVAILABLE"
                self.backoff = min(self.config.max_backoff, max(self.config.interval, self.backoff*2))
                self.next_start = max(self.next_start, finished+self.backoff)
                if self.blocked:
                    for future, _ in self.pending:
                        _finish(future, error=SnapshotUnavailable())
                    self.pending.clear()
            else:
                if self.backoff:
                    logging.getLogger(__name__).info('Adquisición recuperada; reducción gradual de espera.')
                self.metrics["successes"] += 1
                self.last_error = None
                self.backoff = self.backoff/2 if self.backoff > self.config.interval else 0
                self.next_start = max(self.next_start, finished+self.backoff)
                self.state = "RECOVERING" if self.backoff else "READY"
                for future, _ in self.pending:
                    _finish(future, snapshot=self._snapshot)
                self.pending.clear()
            self._save_deadline(acquired, finished)
            published = self._snapshot if error is None else None
            self.condition.notify_all()
        # Consumers only enqueue work here; no business processing or I/O.
        for subscriber in tuple(self.subscribers):
            try:
                subscriber(published)
            except Exception:
                logging.getLogger(__name__).error('Entrega de snapshot fallida; sin detalles sensibles.')
        with self.condition:
            self.inflight = False
            self.condition.notify_all()
        return error is None

    def _save_deadline(self, acquired, monotonic_now):
        if self.lease is not None:
            self.lease.reserve(acquired, max(0, self.next_start-monotonic_now))

    def start(self):
        with self.condition:
            if self.closed:
                raise CoordinatorClosed()
            if self.thread is None:
                self.thread = Thread(target=self._run, name="gps-emi-acquisition", daemon=True)
                self.thread.start()

    def _run(self):
        try:
            while True:
                with self.condition:
                    if self.closed:
                        return
                self.tick()
                with self.condition:
                    if not self.closed:
                        self.condition.wait(timeout=0.2)
        except Exception:
            logging.getLogger(__name__).error('Autoridad de adquisición detenida por fallo interno; sin detalles sensibles.')
        finally:
            with self.condition:
                self.inflight = False
            self.request_stop()
            if self.lease is not None:
                self.lease.close()

    def request_stop(self):
        with self.condition:
            self.closed = True
            self.state = "STOPPED"
            for future, _ in self.pending:
                _finish(future, error=CoordinatorClosed())
            self.pending.clear()
            self.condition.notify_all()

    def close(self, timeout=2):
        self.request_stop()
        if self.thread is not None:
            self.thread.join(timeout)
        elif not self.inflight and self.lease is not None:
            self.lease.close()
        return not self.inflight and (self.thread is None or not self.thread.is_alive())


@dataclass(frozen=True)
class LabelMapping:
    plate_field: str
    mobile_field: str

    def __post_init__(self):
        if {self.plate_field, self.mobile_field} != {"Movil", "VEH_NAM"}:
            raise ValueError("Se requiere mapping explícito Movil/VEH_NAM.")


class SnapshotSource:
    """One projection, explicit consumer scope; all national evidence is retained."""
    def __init__(self, coordinator, mapping=None, *, snapshot=None):
        self.coordinator, self.mapping, self.fixed = coordinator, mapping, snapshot

    def snapshot(self):
        result = self.fixed or self.coordinator.peek()
        if result is None:
            raise SnapshotUnavailable()
        return result

    def bind(self, snapshot):
        return SnapshotSource(self.coordinator, self.mapping, snapshot=snapshot)

    def get_vehicles(self, *, include_retained=True, purpose='query'):
        if purpose not in ('query', 'watch', 'collector'):
            raise ValueError('Política de consumo desconocida.')
        snapshot = self.snapshot()
        if snapshot.result is None:
            return list(snapshot.records)
        if self.mapping is None:
            raise ValueError("Falta mapping explícito de etiquetas.")
        vehicles = []
        metadata = {v.vehicle_id: v for v in (snapshot.catalog.entries if snapshot.catalog else snapshot.identities)}
        for state in snapshot.operational:
            if state.retained_reason is not None and not include_retained:
                continue
            row = state.record
            identity = metadata.get(row.vehicle_id)
            fleet = identity.fleet_name if identity and identity.fleet_name else row.fleet_name
            allowed = bool(fleet and fleet.startswith('Ambulancias')) if purpose == 'query' else fleet in MEDELLIN_FLEETS
            if not allowed:
                continue
            # Existing consumers compare naive Bogota wall times. Preserve the
            # instant by converting before removing tzinfo; originals stay central.
            gps = row.gps_timestamp.astimezone(ZoneInfo("America/Bogota")).replace(tzinfo=None) if row.gps_timestamp else None
            vehicles.append(Vehicle(
                vehid=row.vehicle_id, plate=(identity.plate if identity and identity.plate is not None else normalize_plate(row.raw.get(self.mapping.plate_field) or "")),
                mobile_number=(identity.mobile_number if identity and identity.mobile_number is not None else (row.raw.get(self.mapping.mobile_field) or "").strip()),
                gps_timestamp=gps, location=row.raw.get("Localizacion"), speed=row.speed,
                ignition=row.ignition, gps_fix=row.gps_fix, zones=list(row.zones),
                latitude=row.latitude, longitude=row.longitude, zones_raw=row.raw.get("Zones"),
                vehicle_name_raw=row.raw.get("VEH_NAM"), vehicle_license_raw=row.raw.get("Movil")))
        return vehicles

    def wait(self, timeout=120, *, after_version=None, stop_event=None):
        future = self.coordinator.request(refresh=after_version is not None, after_version=after_version)
        end = self.coordinator.monotonic()+timeout
        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    raise KeyboardInterrupt()
                remaining = end-self.coordinator.monotonic()
                if remaining <= 0:
                    raise SnapshotUnavailable()
                try:
                    return future.result(timeout=min(0.2, remaining))
                except FutureTimeout:
                    pass
        finally:
            future.cancel()


class LegacyAcquisition:
    """Explicit temporary deployment mode, never an error fallback."""
    def __init__(self, client):
        self.client = client

    def acquire(self):
        return tuple(self.client.get_vehicles())
