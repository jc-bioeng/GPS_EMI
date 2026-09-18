from dataclasses import dataclass, field
from datetime import datetime


def normalize_plate(plate: str) -> str:
    return plate.strip().upper()


@dataclass(frozen=True)
class Vehicle:
    vehid: str
    plate: str
    gps_timestamp: datetime | None = None
    location: str | None = None
    speed: float | None = None
    ignition: bool | int | str | None = None
    gps_fix: bool | int | str | None = None
    zones: list[str] = field(default_factory=list)
    mobile_number: str = ""

    @property
    def display_identifier(self) -> str:
        return self.plate or self.mobile_number


@dataclass(frozen=True)
class ArrivalEvent:
    vehicle: Vehicle
    destination: str
    event_type: str = field(default="ARRIVAL_DETECTED", init=False)
    sites: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.sites:
            object.__setattr__(self, "sites", (self.destination,))

    @property
    def site(self) -> str | None:
        """Sede única; si se reportan ambas, no se elige arbitrariamente."""
        return self.sites[0] if len(self.sites) == 1 else None
