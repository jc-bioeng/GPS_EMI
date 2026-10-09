"""Consultas puntuales reutilizables, sin consola, polling ni notificaciones."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math

from gps_emi.config import WatchConfig
from gps_emi.acquisition import SnapshotSource
from gps_emi.models import Vehicle
from gps_emi.monitoring import runner
from gps_emi.monitoring.observation import ObservationAssessment, ObservationValidator
from gps_emi.resolution import find_vehicle, find_vehicle_by_id
from gps_emi.sites import matching_sites, validate_site


class Movement(str, Enum):
    STOPPED = "Detenida"
    MOVING = "En movimiento"


@dataclass(frozen=True)
class AcquisitionInfo:
    epoch: str
    version: int
    acquired_at: datetime
    age_seconds: float
    retained: bool = False
    source: object = None


def _snapshot(client):
    if isinstance(client, SnapshotSource):
        snapshot = client.snapshot()
        age = max(0, (client.coordinator.utcnow()-snapshot.acquired_at).total_seconds())
        return client.bind(snapshot), AcquisitionInfo(snapshot.epoch, snapshot.version, snapshot.acquired_at, age)
    return client, None  # Structural in-memory sources remain useful to domain tests.


def _vehicle_acquisition(client, vehicle, default):
    if isinstance(client, SnapshotSource):
        for state in client.snapshot().operational:
            if state.record.vehicle_id == vehicle.vehid:
                return AcquisitionInfo(state.epoch, state.version, state.acquired_at,
                    max(0, (client.coordinator.utcnow()-state.acquired_at).total_seconds()),
                    state.retained_reason is not None, state.source)
    return default


@dataclass(frozen=True)
class LocationResult:
    vehicle: Vehicle
    queried_at: datetime
    assessment: ObservationAssessment
    stale: bool | None
    acquisition: AcquisitionInfo | None = None

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
    acquisition: AcquisitionInfo | None = None


def describe_vehicle(vehicle: Vehicle, queried_at: datetime, config: WatchConfig, acquisition=None) -> LocationResult:
    # Una consulta es un snapshot independiente, sin histórico de timestamps.
    # Se reutilizan el cálculo de antigüedad y el criterio STALE de I2.
    assessment = ObservationValidator().evaluate(vehicle, queried_at)
    stale = (assessment.is_stale(config.stale_warning_seconds)
             if assessment.report_age is not None else None)
    return LocationResult(vehicle, queried_at, assessment, stale, acquisition)


def get_vehicle_location(client: runner.VehicleSource, identifier: str,
                         config: WatchConfig | None = None, *, now=None) -> LocationResult:
    """Una lectura del snapshot y resolución por placa o móvil."""
    config = config or WatchConfig()
    client, acquisition = _snapshot(client)
    vehicle = find_vehicle(client.get_vehicles(), identifier)
    queried_at = (now if now is not None else runner.local_now)()
    return describe_vehicle(vehicle, queried_at, config, _vehicle_acquisition(client, vehicle, acquisition))


def _inventory_order(result: LocationResult):
    vehicle = result.vehicle
    return (result.report_age is None, bool(result.stale),
            result.report_age if result.report_age is not None else 0,
            vehicle.mobile_number.casefold(), vehicle.plate.casefold(), vehicle.vehid)


def get_vehicle_location_by_id(client: runner.VehicleSource, vehid: str,
                               config: WatchConfig | None = None, *, now=None) -> LocationResult:
    """Lee la identidad seleccionada en el snapshot; no hay fallback por nombre."""
    client, acquisition = _snapshot(client)
    vehicle = find_vehicle_by_id(client.get_vehicles(), vehid)
    return describe_vehicle(vehicle, (now or runner.local_now)(), config or WatchConfig(),
                            _vehicle_acquisition(client, vehicle, acquisition))


def list_vehicles_at_site(client: runner.VehicleSource, site: str,
                          config: WatchConfig | None = None, *, now=None) -> SiteResult:
    """Una lectura para todo el inventario; STALE nunca excluye un registro."""
    validate_site(site)
    config = config or WatchConfig()
    client, acquisition = _snapshot(client)
    vehicles = client.get_vehicles()
    queried_at = (now if now is not None else runner.local_now)()
    entries = [describe_vehicle(vehicle, queried_at, config, _vehicle_acquisition(client, vehicle, acquisition)) for vehicle in vehicles
               if site in matching_sites(vehicle.zones)]
    return SiteResult(site, queried_at, tuple(sorted(entries, key=_inventory_order)), acquisition)
