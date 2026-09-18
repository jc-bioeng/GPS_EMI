"""Consultas puntuales reutilizables, sin consola, polling ni notificaciones."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math

from gps_emi.config import WatchConfig
from gps_emi.models import Vehicle
from gps_emi.monitoring import runner
from gps_emi.monitoring.observation import ObservationAssessment, ObservationValidator
from gps_emi.resolution import find_vehicle
from gps_emi.sites import matching_sites, validate_site


class Movement(str, Enum):
    STOPPED = "Detenida"
    MOVING = "En movimiento"


@dataclass(frozen=True)
class LocationResult:
    vehicle: Vehicle
    queried_at: datetime
    assessment: ObservationAssessment
    stale: bool | None

    @property
    def report_age(self) -> float | None:
        return self.assessment.report_age

    @property
    def movement(self) -> Movement | None:
        speed = self.vehicle.speed
        if not isinstance(speed, (float, int)) or not math.isfinite(speed):
            return None
        if speed == 0:
            return Movement.STOPPED
        if speed > 0:
            return Movement.MOVING
        return None


@dataclass(frozen=True)
class SiteResult:
    site: str
    queried_at: datetime
    entries: tuple[LocationResult, ...]


def _describe(vehicle: Vehicle, queried_at: datetime, config: WatchConfig) -> LocationResult:
    # Una consulta es un snapshot independiente, sin histórico de timestamps.
    # Se reutilizan el cálculo de antigüedad y el criterio STALE de I2.
    assessment = ObservationValidator().evaluate(vehicle, queried_at)
    stale = (assessment.is_stale(config.stale_warning_seconds)
             if assessment.report_age is not None else None)
    return LocationResult(vehicle, queried_at, assessment, stale)


def get_vehicle_location(client: runner.VehicleSource, identifier: str,
                         config: WatchConfig | None = None, *, now=None) -> LocationResult:
    """Una adquisición de la flota filtrada y resolución por placa o móvil."""
    config = config or WatchConfig()
    vehicle = find_vehicle(client.get_vehicles(), identifier)
    queried_at = (now if now is not None else runner.local_now)()
    return _describe(vehicle, queried_at, config)


def _inventory_order(result: LocationResult):
    vehicle = result.vehicle
    return (result.report_age is None, bool(result.stale),
            result.report_age if result.report_age is not None else 0,
            vehicle.mobile_number.casefold(), vehicle.plate.casefold(), vehicle.vehid)


def list_vehicles_at_site(client: runner.VehicleSource, site: str,
                          config: WatchConfig | None = None, *, now=None) -> SiteResult:
    """Una adquisición para todo el inventario; STALE nunca excluye un registro."""
    validate_site(site)
    config = config or WatchConfig()
    vehicles = client.get_vehicles()
    queried_at = (now if now is not None else runner.local_now)()
    entries = [_describe(vehicle, queried_at, config) for vehicle in vehicles
               if site in matching_sites(vehicle.zones)]
    return SiteResult(site, queried_at, tuple(sorted(entries, key=_inventory_order)))
