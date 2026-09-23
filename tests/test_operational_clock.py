from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from unittest.mock import Mock

import pytest

from gps_emi import clock
from gps_emi.monitoring import runner
from gps_emi.monitoring.observation import ObservationStatus, ObservationValidator
from gps_emi.providers.widetech import normalize_vehicle, parse
from gps_emi.queries import get_vehicle_location


@pytest.mark.parametrize('host_zone', ['UTC', 'America/Bogota', 'Asia/Tokyo'])
@pytest.mark.parametrize('age,stale', [(300, False), (301, True), (-1, False)])
def test_provider_age_and_stale_independent_of_host(monkeypatch, host_zone, age, stale):
    instant = datetime(2026, 9, 23, 17, 5, tzinfo=timezone.utc)
    class HostClock:
        @staticmethod
        def now(tz=None):
            # Simula datetime.now() naive del host: el código debe pedir zona.
            if tz is None:
                return instant.astimezone(ZoneInfo(host_zone)).replace(tzinfo=None)
            return instant.astimezone(tz)
    monkeypatch.setenv('TZ', host_zone)
    monkeypatch.setattr(clock, 'datetime', HostClock)
    monkeypatch.setattr(runner, 'local_now', clock.operational_now)
    from datetime import timedelta
    reported = datetime(2026, 9, 23, 12, 5) - timedelta(seconds=age)
    payload = "{'Rows':[{'VEHID':1,'VEH_NAM':'PLATE','Fecha':new Date(%s)}]}" % ','.join(map(str, (reported.year, reported.month-1, reported.day, reported.hour, reported.minute, reported.second)))
    vehicle = normalize_vehicle(parse(payload)[0])
    assert vehicle.gps_timestamp == reported and vehicle.gps_timestamp.tzinfo is None
    source = Mock()
    source.get_vehicles.return_value = [vehicle]
    result = get_vehicle_location(source, 'PLATE')
    assert result.report_age == age and result.stale is stale
    validator = ObservationValidator()
    validator.last_processed_gps_timestamp = reported
    assert validator.evaluate(vehicle, clock.operational_now()).status == ObservationStatus.DUPLICATE
    validator.last_processed_gps_timestamp = reported + timedelta(seconds=1)
    assert validator.evaluate(vehicle, clock.operational_now()).status == ObservationStatus.OUT_OF_ORDER


def test_operational_clock_has_iana_zone_and_naive_compatibility():
    assert clock.BOGOTA.key == 'America/Bogota'
    before = datetime.now(clock.BOGOTA).replace(tzinfo=None)
    actual = clock.operational_now()
    after = datetime.now(clock.BOGOTA).replace(tzinfo=None)
    assert actual.tzinfo is None and before <= actual <= after


def test_utf8_logs_use_bogota_timestamp():
    import io
    import logging
    data = io.BytesIO()
    stream = io.TextIOWrapper(data, encoding='utf-8', newline='\n')
    handler = logging.StreamHandler(stream)
    handler.setFormatter(clock.OperationalFormatter('[%(asctime)s] %(message)s'))
    record = logging.LogRecord('runtime', logging.INFO, '', 0, '🚑 Medellín', (), None)
    record.created = datetime(2026, 9, 23, 17, tzinfo=timezone.utc).timestamp()
    handler.handle(record)
    assert data.getvalue().decode('utf-8') == '[2026-09-23T12:00:00-05:00] 🚑 Medellín\n'
