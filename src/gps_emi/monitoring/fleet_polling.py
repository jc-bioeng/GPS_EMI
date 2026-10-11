"""Distribute central snapshots; no HTTP scheduler or retry policy here."""
from collections import deque
from dataclasses import dataclass, replace
import logging
from threading import Condition, Event, Lock, Thread

from gps_emi.config import WatchConfig
from gps_emi.resolution import find_vehicle, find_vehicle_by_id, VehicleNotFoundError, AmbiguousVehicleError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, repr=False)
class WatchRequest:
    owner_id: str
    identifier: str
    notification_target: str
    vehicle_id: str | None = None
    context_id: str | None = None
    deadline: float = 0
    cancel_generation: int = 0


class FleetPolling:
    def __init__(self, source_factory, manager, *, config=None, on_created=None,
                 on_error=None, on_terminal=None, on_selection=None, thread_factory=Thread,
                 autostart=True, collector=None):
        self.source = source_factory()
        self.coordinator = self.source.coordinator
        self.manager, self.config = manager, config or WatchConfig()
        # Shared clock is installed before any watch is admitted.
        self.manager.monotonic = self.coordinator.monotonic
        self.manager.timing = self.coordinator.watch_timing
        self.on_created, self.on_error = on_created, on_error
        self.on_terminal, self.on_selection = on_terminal, on_selection
        self.collector = collector
        self.thread_factory, self.autostart = thread_factory, autostart
        self.condition, self.cycle_lock = Condition(), Lock()
        self.stop_event = Event()
        self.thread = None
        self.pending, self.snapshots = [], deque()
        self.closed = False
        self.last_version = None
        self.terminal_reported = False
        self.terminal_failures = []
        self.request_valid = lambda request: True
        self.owner_generations = {}
        self.coordinator.probes.append(lambda: self.active)
        self.coordinator.subscribers.append(self._received)

    def collection_active(self):
        return self.collector is not None and self.collector.active is True

    @property
    def active(self):
        with self.condition:
            return not self.closed and not self.coordinator.blocked and (bool(self.pending) or self.manager.has_active() or self.collection_active())

    def _received(self, snapshot):
        # Only enqueue: persistence and notifications stay off the HTTP thread.
        with self.condition:
            if self.closed:
                return
            if snapshot is None:
                if self.coordinator.blocked:
                    # Serialize terminal failure against any queued observation;
                    # channel callbacks still run in the consumer, not HTTP.
                    self.terminal_failures.extend(self.manager.fail_active('acquisition'))
                self.condition.notify_all()
                return
            self.manager.reconcile_identities(snapshot.identities)
            if self.pending or self.manager.has_active():
                if len(self.snapshots) >= self.coordinator.config.capacity:
                    self.snapshots.popleft()
                    logger.warning('Consumidor atrasado; snapshot intermedio omitido.')
                self.snapshots.append(snapshot)
            self.condition.notify_all()
        if self.collection_active():
            try:
                self.collector.submit(self.source.bind(snapshot).get_vehicles(include_retained=False, purpose='collector'),
                                      snapshot.acquired_at, started_at=snapshot.started_at)
            except Exception:
                logger.warning('Collector no disponible; entrega omitida, sin detalles sensibles.')

    def start(self):
        with self.condition:
            if self.autostart and not self.closed and self.thread is None:
                self.thread = self.thread_factory(target=self._run, name='gps-emi-fleet', daemon=True)
                self.thread.start()

    def request_watch(self, owner_id, identifier, notification_target, *, vehicle_id=None, context_id=None):
        if not identifier.strip():
            raise ValueError('Identificador vacío.')
        with self.condition:
            if (self.closed or self.coordinator.closed or self.coordinator.blocked or
                    len(self.pending) >= self.coordinator.config.capacity):
                return False
            request = WatchRequest(owner_id, identifier.strip(), notification_target, vehicle_id, context_id,
                                   self.coordinator.monotonic()+self.coordinator.config.pending_timeout,
                                   self.owner_generations.get(owner_id, 0))
            self.pending.append(request)
            try:
                self.start()
            except Exception:
                self.pending.remove(request)
                raise
            self.condition.notify_all()
        return True

    @staticmethod
    def _callback(callback, *args):
        try:
            if callback is not None:
                callback(*args)
        except Exception:
            logger.error('Callback de vigilancia fallido; sin detalles sensibles.')

    def cancel_pending(self, owner_id):
        with self.condition:
            self.owner_generations[owner_id] = self.owner_generations.get(owner_id, 0)+1
            self.pending = [r for r in self.pending if r.owner_id != owner_id]

    def _valid(self, request):
        return (request.cancel_generation == self.owner_generations.get(request.owner_id, 0)
                and self.request_valid(request))

    def cycle(self):
        with self.cycle_lock:
            with self.condition:
                if self.closed:
                    return
                if self.coordinator.blocked and not self.terminal_reported:
                    self.terminal_reported = True
                    requests, self.pending = self.pending, []
                    failed = self.terminal_failures + self.manager.fail_active('acquisition')
                    self.terminal_failures = []
                    for request in requests:
                        self._callback(self.on_error, request, 'acquisition')
                    for watch in failed:
                        self._callback(self.on_terminal, watch)
                    return
                self.manager.tick()
                if not self.pending and not self.snapshots and not self.manager.has_active():
                    return
                now = self.coordinator.monotonic()
                expired = [r for r in self.pending if self._valid(r) and now >= r.deadline]
                self.pending = [r for r in self.pending if self._valid(r) and now < r.deadline]
                snapshot = self.snapshots.popleft() if self.snapshots else self.coordinator.peek()
                # Drain older observations before admitting new watches. Otherwise
                # an old queued fleet could override an already confirmed change.
                requests, self.pending = ((self.pending, []) if snapshot is not None and not self.snapshots
                                          else ([], self.pending))
            for request in expired:
                self._callback(self.on_error, request, 'acquisition')
            if snapshot is None:
                return
            version = (snapshot.epoch, snapshot.version)
            if version == self.last_version and not requests:
                return
            current = self.coordinator.peek()
            # Observation order stays intact; identity metadata must not regress
            # while draining a backlog. Original GPS records remain untouched.
            projected = (replace(snapshot, catalog=current.catalog, identities=current.identities)
                         if current is not None else snapshot)
            vehicles = self.source.bind(projected).get_vehicles(include_retained=False, purpose='watch')
            created, errors, selections = [], [], []
            with self.condition:
                if self.closed:
                    return
                for request in requests:
                    if not self._valid(request):
                        continue
                    try:
                        vehicle = (find_vehicle_by_id(vehicles, request.vehicle_id) if request.vehicle_id is not None
                                   else find_vehicle(vehicles, request.identifier))
                        if not vehicle.vehid:
                            raise ValueError('Falta identidad técnica.')
                        vehicle = find_vehicle_by_id(vehicles, vehicle.vehid)
                        created.append(self.manager.create_watch(request.owner_id, vehicle, request.notification_target))
                    except VehicleNotFoundError:
                        errors.append((request, 'selected_unavailable' if request.vehicle_id is not None else 'not_found'))
                    except AmbiguousVehicleError as error:
                        if request.vehicle_id is None and error.candidates and self.on_selection is not None:
                            selections.append((request, error.candidates))
                        else:
                            errors.append((request, 'selected_unavailable' if request.vehicle_id is not None else 'ambiguous'))
                    except Exception:
                        errors.append((request, 'identity'))
            only_new = {w.watch_id for w, new in created if new} if version == self.last_version else None
            self.manager.reconcile_identities(projected.catalog.entries if projected.catalog else projected.identities)
            self.manager.process_snapshot(vehicles, watch_ids=only_new)
            self.last_version = version
            from gps_emi.observability import metrics
            metrics.update(active_watches=self.manager.active_count())
            for watch, is_new in created:
                self._callback(self.on_created, self.manager.get_watch(watch.owner_id, watch.watch_id), is_new)
            for request, code in errors:
                self._callback(self.on_error, request, code)
            for request, candidates in selections:
                self._callback(self.on_selection, request, candidates)

    def _run(self):
        try:
            while not self.stop_event.is_set():
                self.cycle()
                with self.condition:
                    # This timeout expires pending registrations; never acquires.
                    if (not self.snapshots and not self.closed and
                            not (self.coordinator.blocked and not self.terminal_reported)):
                        self.condition.wait(timeout=0.2 if self.pending or self.manager.has_active() else None)
        except Exception:
            logger.error('Distribución detenida por fallo interno; sin detalles sensibles.')
            with self.condition:
                requests, self.pending = self.pending, []
                failed = self.manager.fail_active('internal')
                self.closed = True
            for request in requests:
                self._callback(self.on_error, request, 'internal')
            for watch in failed:
                self._callback(self.on_terminal, watch)

    def request_stop(self):
        with self.condition:
            self.closed = True
            self.pending.clear()
            self.snapshots.clear()
            self.stop_event.set()
            self.manager.close()
            self.condition.notify_all()

    def close(self, timeout=2):
        self.request_stop()
        if self.thread is not None:
            self.thread.join(timeout=timeout)
        return self.thread is None or not self.thread.is_alive()
