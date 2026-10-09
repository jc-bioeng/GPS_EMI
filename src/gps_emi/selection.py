"""Contextos de selección independientes del canal, en memoria y consumibles una vez."""
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from threading import RLock
import time
from uuid import uuid4

from gps_emi.models import Vehicle
from gps_emi.config import WatchConfig
from gps_emi.monitoring import runner
from gps_emi.queries import LocationResult, describe_vehicle


class SelectionOperation(str, Enum):
    LOCATION = 'LOCATION'
    CREATE_WATCH = 'CREATE_WATCH'


class SelectionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class PendingVehicleSelection:
    selection_id: str
    owner_id: str
    operation: SelectionOperation
    original_identifier: str
    candidates: tuple[Vehicle, ...]
    created_at: float  # Reloj monotónico; solo se usa para TTL.
    notification_target: str
    choice_ids: tuple[str, ...]
    candidate_reports: tuple[LocationResult, ...]


class PendingSelections:
    def __init__(self, *, ttl=300, now=None, config=None):
        self.ttl, self.now = ttl, now or time.monotonic
        self.config = config or WatchConfig()
        self._lock = RLock()
        self._pending, self._generation = {}, {}

    def begin(self, owner_id):
        """Invalida también ofertas asíncronas de una operación anterior."""
        with self._lock:
            self._pending.pop(owner_id, None)
            generation = uuid4().hex
            self._generation[owner_id] = generation
            return generation

    def current(self, owner_id):
        with self._lock:
            return self._generation.get(owner_id)

    def offer(self, owner_id, operation, identifier, candidates, target, generation, *, reports=()):
        with self._lock:
            if generation is None or generation != self._generation.get(owner_id):
                return None
            # No fingir que dos filas con el mismo VEHID se pueden distinguir.
            ids = [v.vehid for v in candidates]
            if len(ids) < 2 or any(not vid for vid in ids) or len(set(ids)) != len(ids):
                raise SelectionError('unavailable')
            candidates = deepcopy(tuple(candidates))
            if reports and tuple(r.vehicle.vehid for r in reports) != tuple(ids):
                raise SelectionError('unavailable')
            observed_at = runner.local_now()
            context = PendingVehicleSelection(uuid4().hex, owner_id, operation, identifier,
                candidates, self.now(), target, tuple(uuid4().hex for _ in candidates),
                deepcopy(tuple(reports)) if reports else tuple(describe_vehicle(v, observed_at, self.config) for v in candidates))
            self._pending[owner_id] = context
            return deepcopy(context)

    def _get(self, owner_id, selection_id):
        context = self._pending.get(owner_id)
        if context is None or context.selection_id != selection_id:
            raise SelectionError('invalid')
        if self.now() - context.created_at >= self.ttl:
            self._pending.pop(owner_id, None)
            raise SelectionError('expired')
        return context

    def view(self, owner_id, selection_id):
        with self._lock:
            return deepcopy(self._get(owner_id, selection_id))

    def consume(self, owner_id, selection_id, choice_id):
        with self._lock:
            context = self._get(owner_id, selection_id)
            if choice_id not in context.choice_ids:
                raise SelectionError('invalid')
            candidate = context.candidates[context.choice_ids.index(choice_id)]
            self._pending.pop(owner_id)
            # Cierra también las ofertas tardías de la operación consumida.
            self._generation[owner_id] = uuid4().hex
            return deepcopy(context), candidate.vehid
