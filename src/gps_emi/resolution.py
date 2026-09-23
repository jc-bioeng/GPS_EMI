"""Resolución sobre los vehículos de la flota autorizada que entrega el cliente."""
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
import re

from gps_emi.models import Vehicle


class VehicleResolutionError(ValueError):
    """No es posible seleccionar un único móvil."""


class VehicleNotFoundError(VehicleResolutionError):
    pass


class AmbiguousVehicleError(VehicleResolutionError):
    def __init__(self, message, candidates=()):
        super().__init__(message)
        self.candidates = tuple(candidates)


class ResolutionStatus(str, Enum):
    NOT_FOUND = 'NOT_FOUND'
    RESOLVED = 'RESOLVED'
    AMBIGUOUS = 'AMBIGUOUS'


@dataclass(frozen=True, repr=False)
class VehicleResolution:
    status: ResolutionStatus
    candidates: tuple[Vehicle, ...]

    @property
    def vehicle(self):
        return self.candidates[0] if self.status == ResolutionStatus.RESOLVED else None


def identifier_key(value: str) -> str:
    key = value.strip().casefold()
    return re.sub(r"^amb-?([0-9]+)$", r"amb-\1", key)


def resolve_vehicle(vehicles: Iterable[Vehicle], identifier: str) -> VehicleResolution:
    """Coincidencia en ambos campos con alias AMB20/AMB-20, sin prioridades.

    La colección debe provenir de WideTechClient.get_vehicles(), que aplica el
    filtro de flota. Una fila que coincida en ambos campos cuenta una sola vez.
    """
    key = identifier_key(identifier)
    matches = [vehicle for vehicle in vehicles if key and any(
        identifier_key(value) == key
        for value in (vehicle.plate, vehicle.mobile_number)
    )]
    status = ResolutionStatus.NOT_FOUND if not matches else ResolutionStatus.RESOLVED if len(matches) == 1 else ResolutionStatus.AMBIGUOUS
    return VehicleResolution(status, tuple(matches))


def find_vehicle(vehicles: Iterable[Vehicle], identifier: str) -> Vehicle:
    """Interfaz fail-safe conservada para CLI y consumidores existentes."""
    result = resolve_vehicle(vehicles, identifier)
    if result.status == ResolutionStatus.NOT_FOUND:
        raise VehicleNotFoundError("No se encontró el móvil entre Ambulancias Medellín.")
    if result.status == ResolutionStatus.AMBIGUOUS:
        raise AmbiguousVehicleError(
            "El identificador es ambiguo: coincide con varios móviles de Ambulancias Medellín.", result.candidates
        )
    return result.vehicle


def find_vehicle_by_id(vehicles: Iterable[Vehicle], vehid: str) -> Vehicle:
    """Continuidad de una vigilancia ya resuelta, sobre la misma flota filtrada."""
    matches = [vehicle for vehicle in vehicles if vehicle.vehid == vehid]
    if not matches:
        raise VehicleNotFoundError("El VEHID vigilado no aparece temporalmente en la consulta.")
    if len(matches) > 1:
        raise AmbiguousVehicleError("El VEHID vigilado es ambiguo en la respuesta.")
    return matches[0]
