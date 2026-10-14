"""Shared temporal gate for CLI and managed watches; never acquires data."""
from dataclasses import dataclass

from gps_emi.models import PresenceEvent
from gps_emi.sites import matching_sites
from .arrival import MonitorState
from .observation import ObservationStatus, observe_resolved_vehicle


@dataclass
class Continuity:
    activity_at: float
    interrupted: bool = False
    recovery_site: str | None = None
    recovery_count: int = 0
    expired: bool = False
    require_exit: bool = False

    def tick(self, now, config, timing):
        # Individual monotonic duration is never discounted by an outage.
        if now - self.activity_at >= 300 and not self.interrupted:
            self.interrupted = True
            self.recovery_site, self.recovery_count = None, 0
        elif now - self.activity_at >= 300 and self.recovery_count:
            self.recovery_site, self.recovery_count = None, 0
        elapsed, inflight = timing(self.activity_at)
        # A pending attempt may establish a pause retroactively at its start.
        if not inflight and elapsed > config.inactivity_seconds:
            self.expired = True
        return self.expired

    def observe(self, vehicle, now, wall_now, config, timing, monitor, validator, vehicle_id):
        assessment = validator.evaluate(vehicle, wall_now)
        if self.tick(now, config, timing) or assessment.status != ObservationStatus.NEW:
            return assessment, None
        # This fixed safety boundary is independent of the display warning option.
        if assessment.is_stale(300):
            return assessment, None
        validator.last_processed_gps_timestamp = vehicle.gps_timestamp
        self.activity_at = now
        if self.require_exit:
            # An accepted watch that started inside must witness a fresh exit.
            # Recovery inside is not a substitute for the user's requested trip.
            sites = matching_sites(vehicle.zones)
            monitor.actual_sites = sites
            if sites:
                return assessment, None
            self.require_exit = False
            self.interrupted = False
            self.recovery_site, self.recovery_count = None, 0
            monitor.state = MonitorState.INITIAL
            observe_resolved_vehicle(monitor, vehicle, vehicle_id)
            return assessment, None
        if not self.interrupted:
            return assessment, observe_resolved_vehicle(monitor, vehicle, vehicle_id)
        sites = matching_sites(vehicle.zones)
        if monitor.destination is not None:
            sites = tuple(s for s in sites if s == monitor.destination)
        if not sites:
            self.interrupted = False
            self.recovery_site, self.recovery_count = None, 0
            monitor.state = MonitorState.INITIAL
            observe_resolved_vehicle(monitor, vehicle, vehicle_id)
            return assessment, None
        # Multiple reported sites cannot establish a unique confirmation site.
        site = sites[0] if len(sites) == 1 else None
        self.recovery_count = self.recovery_count + 1 if site and site == self.recovery_site else (1 if site else 0)
        self.recovery_site = site
        monitor.actual_sites = sites
        if self.recovery_count == 3:
            monitor.state = MonitorState.ARRIVAL_DETECTED
            return assessment, PresenceEvent(vehicle, site, sites=(site,))
        return assessment, None
