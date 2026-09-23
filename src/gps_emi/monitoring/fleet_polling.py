"""Una adquisición por ciclo para altas pendientes y todas las Watches activas."""
from dataclasses import dataclass
import logging
from threading import Condition, Event, Lock, Thread

from gps_emi.config import WatchConfig
from gps_emi.errors import AcquisitionError, TransientAcquisitionError
from gps_emi.resolution import find_vehicle, find_vehicle_by_id, VehicleNotFoundError, AmbiguousVehicleError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, repr=False)
class WatchRequest:
    owner_id: str
    identifier: str
    notification_target: str
    vehicle_id: str | None = None
    context_id: str | None = None


class FleetPolling:
    def __init__(self, source_factory, manager, *, config=None, on_created=None,
                 on_error=None, on_terminal=None, on_selection=None, thread_factory=Thread, autostart=True):
        self.source_factory, self.manager = source_factory, manager
        self.config = config or WatchConfig()
        self.on_created, self.on_error, self.on_terminal = on_created, on_error, on_terminal
        self.on_selection = on_selection
        self.thread_factory, self.autostart = thread_factory, autostart
        self.condition, self.cycle_lock = Condition(), Lock()
        self.stop_event = Event()
        self.thread = None
        self.pending = []
        self.closed = False
        self.consecutive_failures = 0
        self.next_backoff = self.config.initial_backoff

    @property
    def active(self):
        with self.condition:
            return bool(self.pending) or self.manager.has_active()

    def request_watch(self, owner_id, identifier, notification_target, *, vehicle_id=None, context_id=None):
        if not identifier.strip():
            raise ValueError('Identificador vacío.')
        with self.condition:
            if self.closed:
                return False
            request = WatchRequest(owner_id, identifier.strip(), notification_target, vehicle_id, context_id)
            self.pending.append(request)
            try:
                if self.autostart and self.thread is None:
                    thread = self.thread_factory(target=self._run, name='gps-emi-fleet', daemon=True)
                    thread.start()
                    self.thread = thread
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

    def cycle(self):
        with self.cycle_lock:
            with self.condition:
                if self.closed or self.stop_event.is_set():
                    return None
                requests = list(self.pending)
                if not requests and not self.manager.has_active():
                    return None
            try:
                vehicles = list(self.source_factory().get_vehicles())
            except TransientAcquisitionError:
                self.consecutive_failures += 1
                delay = self.next_backoff
                self.next_backoff = min(delay * 2, self.config.max_backoff)
                logger.warning('Adquisición recuperable fallida; intento=%d espera=%g s.', self.consecutive_failures, delay)
                return delay
            except Exception as error:
                code = 'acquisition' if isinstance(error, AcquisitionError) else 'internal'
                with self.condition:
                    if self.closed or self.stop_event.is_set():
                        return None
                    requests, self.pending = self.pending, []
                    failed = self.manager.fail_active(code)
                self.consecutive_failures = 0
                self.next_backoff = self.config.initial_backoff
                logger.error('Adquisición terminal; vigilancias detenidas, sin inferir llegadas.')
                for request in requests:
                    self._callback(self.on_error, request, code)
                for watch in failed:
                    self._callback(self.on_terminal, watch)
                return None
            with self.condition:
                if self.closed or self.stop_event.is_set():
                    return None
                # Nuevas solicitudes durante HTTP esperan el siguiente snapshot.
                del self.pending[:len(requests)]
                created = []
                errors = []
                selections = []
                for request in requests:
                    try:
                        vehicle = (find_vehicle_by_id(vehicles, request.vehicle_id) if request.vehicle_id is not None
                                   else find_vehicle(vehicles, request.identifier))
                        if not vehicle.vehid:
                            raise ValueError('Falta identidad técnica.')
                        vehicle = find_vehicle_by_id(vehicles, vehicle.vehid)
                        watch, is_new = self.manager.create_watch(request.owner_id, vehicle, request.notification_target)
                        created.append((watch, is_new))
                    except VehicleNotFoundError:
                        errors.append((request, 'selected_unavailable' if request.vehicle_id is not None else 'not_found'))
                    except AmbiguousVehicleError as error:
                        if request.vehicle_id is None and error.candidates and self.on_selection is not None:
                            selections.append((request, error.candidates))
                        else:
                            errors.append((request, 'selected_unavailable' if request.vehicle_id is not None else 'ambiguous'))
                    except Exception:
                        errors.append((request, 'identity'))
            if self.consecutive_failures:
                logger.info('Adquisición recuperada; polling normal restaurado.')
            self.consecutive_failures = 0
            self.next_backoff = self.config.initial_backoff
            # La confirmación usa la primera observación ya evaluada, sin otra adquisición.
            self.manager.process_snapshot(vehicles)
            for watch, is_new in created:
                if is_new:
                    watch = self.manager.get_watch(watch.owner_id, watch.watch_id)
                self._callback(self.on_created, watch, is_new)
            for request, code in errors:
                self._callback(self.on_error, request, code)
            for request, candidates in selections:
                self._callback(self.on_selection, request, candidates)
            return self.config.polling_interval

    def _run(self):
        try:
            while not self.stop_event.is_set():
                with self.condition:
                    self.condition.wait_for(lambda: self.closed or self.stop_event.is_set() or self.active)
                    if self.closed or self.stop_event.is_set():
                        break
                delay = self.cycle()
                if delay is not None and self.active and self.stop_event.wait(delay):
                    break
        except Exception:
            # Un fallo inesperado del loop no deja Watches activas sin consumidor.
            with self.condition:
                requests, self.pending = self.pending, []
                failed = self.manager.fail_active('internal')
                self.closed = True
            logger.error('Polling detenido por fallo interno; sin detalles sensibles.')
            for request in requests:
                self._callback(self.on_error, request, 'internal')
            for watch in failed:
                self._callback(self.on_terminal, watch)
        finally:
            logger.info('Polling de flota detenido.')

    def close(self, timeout=2):
        with self.condition:
            self.closed = True
            self.pending.clear()
            self.stop_event.set()
            self.manager.close()
            self.condition.notify_all()
            thread = self.thread
        if thread is not None:
            thread.join(timeout=timeout)
        return thread is None or not thread.is_alive()
