from datetime import datetime, timedelta, timezone

import pytest

from gps_emi.models import Vehicle
from gps_emi.monitoring.arrival import ArrivalMonitor, DESTINATIONS
from gps_emi.monitoring.observation import ObservationValidator, ObservationStatus, observe_resolved_vehicle

BASE = datetime(2026, 9, 17, 12, 30)


@pytest.mark.parametrize('seconds,status', [
    (-60, ObservationStatus.OUT_OF_ORDER), (0, ObservationStatus.DUPLICATE),
    (60, ObservationStatus.NEW),
])
def test_timestamp_order_and_report_age(seconds, status):
    validator = ObservationValidator()
    validator.last_processed_gps_timestamp = BASE
    vehicle = Vehicle('1', 'ABC123', gps_timestamp=BASE + timedelta(seconds=seconds))
    result = validator.evaluate(vehicle, BASE + timedelta(minutes=5))
    assert result.status == status
    assert result.report_age == 300 - seconds
    # Solo el runner confirma el timestamp después de observar en el dominio.
    assert validator.last_processed_gps_timestamp == BASE


def test_missing_timestamp():
    result = ObservationValidator().evaluate(Vehicle('1', 'ABC123'), BASE)
    assert result.status == ObservationStatus.MISSING_TIMESTAMP
    assert result.report_age is None


@pytest.mark.parametrize('timestamp,now,previous', [
    (BASE, BASE.replace(tzinfo=timezone.utc), None),
    (BASE.replace(tzinfo=timezone.utc), BASE, None),
    (BASE, BASE, BASE.replace(tzinfo=timezone.utc)),
])
def test_timezone_mismatch_is_not_guessed(timestamp, now, previous):
    validator = ObservationValidator()
    validator.last_processed_gps_timestamp = previous
    result = validator.evaluate(Vehicle('1', 'ABC123', gps_timestamp=timestamp), now)
    assert result.status == ObservationStatus.TIMEZONE_MISMATCH
    assert validator.last_processed_gps_timestamp == previous


def test_aware_dates_compare_instants():
    timestamp = BASE.replace(tzinfo=timezone(timedelta(hours=-5)))
    now = datetime(2026, 9, 17, 17, 31, tzinfo=timezone.utc)
    result = ObservationValidator().evaluate(Vehicle('1', 'ABC123', gps_timestamp=timestamp), now)
    assert result.status == ObservationStatus.NEW
    assert result.report_age == 60


def test_identity_bridge_does_not_accept_other_vehid():
    monitor = ArrivalMonitor('ABC123', DESTINATIONS[0])
    with pytest.raises(ValueError, match='VEHID'):
        observe_resolved_vehicle(monitor, Vehicle('other', 'ABC123'), expected_vehid='1')
