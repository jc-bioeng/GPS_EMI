"""Validación temporal y adaptación al monitor determinista de I1."""
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum

from gps_emi.models import ArrivalEvent, Vehicle
from gps_emi.monitoring.arrival import ArrivalMonitor


class ObservationStatus(str, Enum):
    NEW = "NEW"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    MISSING_TIMESTAMP = "MISSING_TIMESTAMP"
    TIMEZONE_MISMATCH = "TIMEZONE_MISMATCH"


@dataclass(frozen=True)
class ObservationAssessment:
    status: ObservationStatus
    report_age: float | None = None

    def is_stale(self, threshold: float) -> bool:
        return self.report_age is not None and self.report_age > threshold


def gps_fix_warning(value) -> bool:
    return value in (0, False, "0")


class ObservationValidator:
    def __init__(self):
        self.last_processed_gps_timestamp: datetime | None = None

    def evaluate(self, vehicle: Vehicle, now: datetime) -> ObservationAssessment:
        timestamp = vehicle.gps_timestamp
        if timestamp is None:
            return ObservationAssessment(ObservationStatus.MISSING_TIMESTAMP)
        previous = self.last_processed_gps_timestamp
        if ((timestamp.utcoffset() is None) != (now.utcoffset() is None)
                or (previous is not None and
                    (timestamp.utcoffset() is None) != (previous.utcoffset() is None))):
            return ObservationAssessment(ObservationStatus.TIMEZONE_MISMATCH)
        age = (now - timestamp).total_seconds()
        if previous is not None:
            if timestamp < previous:
                return ObservationAssessment(ObservationStatus.OUT_OF_ORDER, age)
            if timestamp == previous:
                return ObservationAssessment(ObservationStatus.DUPLICATE, age)
        return ObservationAssessment(ObservationStatus.NEW, age)


def observe_resolved_vehicle(monitor: ArrivalMonitor, vehicle: Vehicle,
                             expected_vehid: str | None = None) -> ArrivalEvent | None:
    # I1 exige un atributo plate estable y no vacío. Se adapta solo la copia
    # de entrada; el evento siempre conserva el Vehicle recibido originalmente.
    if expected_vehid is not None:
        if not expected_vehid or vehicle.vehid != expected_vehid:
            raise ValueError("La observación no corresponde al VEHID vigilado.")
        # El runner ya comprobó identidad estable. La interfaz heredada del
        # monitor recibe su clave inicial aunque cambie la representación visible.
        observation = replace(vehicle, plate=monitor.plate)
    else:
        observation = vehicle if vehicle.plate else replace(vehicle, plate=vehicle.mobile_number)
    event = monitor.observe(observation)
    return replace(event, vehicle=vehicle) if event is not None else None
