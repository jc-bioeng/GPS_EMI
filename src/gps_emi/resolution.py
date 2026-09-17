"""Resolución sobre los vehículos de la flota autorizada que entrega el cliente."""
from collections.abc import Iterable

from gps_emi.models import Vehicle


class VehicleResolutionError(ValueError):
    """No es posible seleccionar un único móvil."""


class VehicleNotFoundError(VehicleResolutionError):
    pass


class AmbiguousVehicleError(VehicleResolutionError):
    pass


def find_vehicle(vehicles: Iterable[Vehicle], identifier: str) -> Vehicle:
    """Coincidencia exacta en cualquiera de los dos campos, sin priorizar uno.

    La colección debe provenir de WideTechClient.get_vehicles(), que aplica el
    filtro de flota. Una fila que coincida en ambos campos cuenta una sola vez.
    """
    key = identifier.strip().casefold()
    matches = [vehicle for vehicle in vehicles if key and any(
        value.strip().casefold() == key
        for value in (vehicle.plate, vehicle.mobile_name)
    )]
    if not matches:
        raise VehicleNotFoundError("No se encontró el móvil entre Ambulancias Medellín.")
    if len(matches) > 1:
        raise AmbiguousVehicleError(
            "El identificador es ambiguo: coincide con varios móviles de Ambulancias Medellín."
        )
    return matches[0]
