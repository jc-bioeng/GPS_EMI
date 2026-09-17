from enum import Enum

from gps_emi.models import ArrivalEvent, Vehicle, normalize_plate

DESTINATIONS = ("EMI Medellin_Poblado", "EMI_Medellin_Taller")


class MonitorState(str, Enum):
    INITIAL = "INITIAL"
    OUTSIDE = "OUTSIDE"
    INSIDE = "INSIDE"
    ARRIVAL_DETECTED = "ARRIVAL_DETECTED"


class ArrivalMonitor:
    def __init__(self, plate: str, destination: str):
        self.plate = normalize_plate(plate)
        if not self.plate:
            raise ValueError("La placa no puede estar vacía.")
        if destination not in DESTINATIONS:
            raise ValueError("Destino no permitido.")
        self.destination = destination
        self.state = MonitorState.INITIAL

    def observe(self, vehicle: Vehicle) -> ArrivalEvent | None:
        if normalize_plate(vehicle.plate) != self.plate:
            raise ValueError("La observación no corresponde a la placa vigilada.")
        if self.state == MonitorState.ARRIVAL_DETECTED:
            return None
        inside = self.destination in vehicle.zones
        if self.state == MonitorState.OUTSIDE and inside:
            self.state = MonitorState.ARRIVAL_DETECTED
            return ArrivalEvent(vehicle, self.destination)
        self.state = MonitorState.INSIDE if inside else MonitorState.OUTSIDE
        return None
