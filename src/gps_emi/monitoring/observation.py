"""Compatibilidad con la interfaz de ArrivalMonitor de I1, sin alterar su lógica."""
from dataclasses import replace

from gps_emi.models import ArrivalEvent, Vehicle
from gps_emi.monitoring.arrival import ArrivalMonitor


def observe_resolved_vehicle(monitor: ArrivalMonitor, vehicle: Vehicle) -> ArrivalEvent | None:
    # I1 exige un atributo plate no vacío. Solo la copia de entrada utiliza el
    # número VEH_LCNS para móviles sin placa VEH_NAM; nunca se modifica el
    # Vehicle resuelto ni se publica esa copia como datos normalizados.
    observation = vehicle if vehicle.plate else replace(vehicle, plate=vehicle.mobile_number)
    event = monitor.observe(observation)
    return replace(event, vehicle=vehicle) if event is not None else None
