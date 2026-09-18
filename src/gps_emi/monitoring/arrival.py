from enum import Enum

from gps_emi.models import ArrivalEvent, Vehicle, normalize_plate
from gps_emi.sites import EMI_SITES, matching_sites

DESTINATIONS = EMI_SITES  # Nombre histórico para consumidores de I1/I2.


class MonitorState(str, Enum):
    INITIAL = "INITIAL"
    OUTSIDE = "OUTSIDE"
    INSIDE = "INSIDE"
    OUTSIDE_EMI = "OUTSIDE_EMI"
    INSIDE_EMI = "INSIDE_EMI"
    ARRIVAL_DETECTED = "ARRIVAL_DETECTED"


class ArrivalMonitor:
    def __init__(self, plate: str, destination: str | None = None):
        self.plate = normalize_plate(plate)
        if not self.plate:
            raise ValueError("La placa no puede estar vacía.")
        if destination is not None and destination not in DESTINATIONS:
            raise ValueError("Destino no permitido.")
        self.destination = destination
        self.state = MonitorState.INITIAL
        self.actual_sites: tuple[str, ...] = ()

    @property
    def actual_site(self) -> str | None:
        return self.actual_sites[0] if len(self.actual_sites) == 1 else None

    def observe(self, vehicle: Vehicle) -> ArrivalEvent | None:
        if normalize_plate(vehicle.plate) != self.plate:
            raise ValueError("La observación no corresponde a la placa vigilada.")
        if self.state == MonitorState.ARRIVAL_DETECTED:
            return None
        self.actual_sites = matching_sites(vehicle.zones)
        # destination explícito conserva temporalmente el modo de una sede de I2.
        sites = (tuple(site for site in self.actual_sites if site == self.destination)
                 if self.destination is not None else self.actual_sites)
        inside = bool(sites)
        outside_state = MonitorState.OUTSIDE if self.destination is not None else MonitorState.OUTSIDE_EMI
        inside_state = MonitorState.INSIDE if self.destination is not None else MonitorState.INSIDE_EMI
        if self.state == outside_state and inside:
            self.state = MonitorState.ARRIVAL_DETECTED
            return ArrivalEvent(vehicle, " / ".join(sites), sites=sites)
        self.state = inside_state if inside else outside_state
        return None
