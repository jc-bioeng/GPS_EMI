from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from gps_emi.config import WatchConfig
from gps_emi.errors import SessionExpiredError, TransientAcquisitionError
from gps_emi.models import Vehicle
from gps_emi.providers.widetech import LegacyWideTechTransport as WideTechClient, normalize_vehicle, parse
from gps_emi.queries import get_vehicle_location, list_vehicles_at_site, Movement
from gps_emi.resolution import VehicleNotFoundError, AmbiguousVehicleError
from gps_emi.sites import EMI_SITES

NOW = datetime(2026, 9, 17, 12, 35)
POBLADO, TALLER = EMI_SITES


@pytest.fixture
def observed_vehicle(observed_amb20_payload):
    vehicle = normalize_vehicle(parse(observed_amb20_payload)[0])
    # Solo identidad/flota son valores observados; telemetría de prueba sintética.
    return replace(vehicle, location='COL - RIONEGRO (ANT) - CR 39 CON CR 38',
                   gps_timestamp=NOW - timedelta(seconds=43), speed=37, ignition=1, gps_fix=1)


@pytest.mark.parametrize('identifier', ['AMB-20', 'PJU886', ' amb-20 ', ' pju886 '])
def test_location_uses_existing_resolution_and_one_acquisition(identifier, observed_vehicle, monkeypatch):
    client = Mock()
    client.get_vehicles.return_value = [observed_vehicle]
    def forbidden(*args, **kwargs):
        pytest.fail('Una consulta puntual no debe iniciar vigilancia')
    monkeypatch.setattr('gps_emi.monitoring.runner.WatchRunner', forbidden)
    monkeypatch.setattr('gps_emi.monitoring.runner.ArrivalMonitor', forbidden)
    result = get_vehicle_location(client, identifier, now=lambda: NOW)
    client.get_vehicles.assert_called_once_with()
    assert result.vehicle is observed_vehicle
    assert result.vehicle.vehid == '433909'
    assert result.vehicle.mobile_number == 'AMB-20'
    assert result.vehicle.plate == 'PJU886'
    assert result.vehicle.location == observed_vehicle.location
    assert result.vehicle.gps_timestamp == observed_vehicle.gps_timestamp
    assert result.vehicle.ignition == 1
    assert result.vehicle.gps_fix == 1
    assert result.report_age == 43
    assert result.queried_at == NOW
    assert result.stale is False


def test_mobile_and_plate_queries_return_same_vehicle(observed_vehicle):
    client = Mock()
    client.get_vehicles.return_value = [observed_vehicle]
    by_number = get_vehicle_location(client, 'AMB-20', now=lambda: NOW)
    by_plate = get_vehicle_location(client, 'PJU886', now=lambda: NOW)
    assert by_number.vehicle is by_plate.vehicle
    assert client.get_vehicles.call_count == 2  # Una adquisición por consulta.


@pytest.mark.parametrize('speed,expected', [
    (0, Movement.STOPPED), (37, Movement.MOVING), (0.1, Movement.MOVING),
    (None, None), (-1, None), (float('nan'), None), (float('inf'), None),
])
def test_speed_interpretation(speed, expected, observed_vehicle):
    client = Mock()
    client.get_vehicles.return_value = [replace(observed_vehicle, speed=speed)]
    result = get_vehicle_location(client, 'AMB-20', now=lambda: NOW)
    assert result.movement == expected
    assert result.vehicle.speed is speed


@pytest.mark.parametrize('age,threshold,expected', [(43, 300, False), (300, 300, False),
                                                 (301, 300, True), (786, 300, True), (43, 20, True)])
def test_stale_matches_i2_policy(age, threshold, expected, observed_vehicle):
    client = Mock()
    client.get_vehicles.return_value = [replace(observed_vehicle, gps_timestamp=NOW - timedelta(seconds=age))]
    result = get_vehicle_location(client, 'AMB-20', WatchConfig(stale_warning_seconds=threshold), now=lambda: NOW)
    assert result.stale is expected
    assert result.report_age == age
    assert result.vehicle.location == observed_vehicle.location


@pytest.mark.parametrize('timestamp', [None, NOW.replace(tzinfo=timezone.utc)])
def test_missing_or_incomparable_timestamp_is_retained(timestamp, observed_vehicle):
    client = Mock()
    client.get_vehicles.return_value = [replace(observed_vehicle, gps_timestamp=timestamp)]
    result = get_vehicle_location(client, 'PJU886', now=lambda: NOW)
    assert result.report_age is None
    assert result.stale is None
    assert result.vehicle.gps_timestamp == timestamp


def test_gpsfix_zero_does_not_hide_location(observed_vehicle):
    client = Mock()
    client.get_vehicles.return_value = [replace(observed_vehicle, gps_fix=0)]
    assert get_vehicle_location(client, 'AMB-20', now=lambda: NOW).vehicle.location == observed_vehicle.location


@pytest.mark.parametrize('rows,error', [([], VehicleNotFoundError),
                                      ([Vehicle('1', 'X'), Vehicle('2', 'X')], AmbiguousVehicleError)])
def test_location_resolution_errors(rows, error):
    client = Mock()
    client.get_vehicles.return_value = rows
    with pytest.raises(error):
        get_vehicle_location(client, 'X', now=lambda: NOW)
    client.get_vehicles.assert_called_once()


@pytest.mark.parametrize('error', [TransientAcquisitionError(), SessionExpiredError()])
@pytest.mark.parametrize('operation', ['location', 'site'])
def test_queries_never_retry(error, operation):
    client = Mock()
    client.get_vehicles.side_effect = error
    with pytest.raises(type(error)):
        if operation == 'location':
            get_vehicle_location(client, 'AMB-20')
        else:
            list_vehicles_at_site(client, POBLADO)
    client.get_vehicles.assert_called_once()


def report(vehid, age, zones):
    return Vehicle(vehid, f'PLATE-{vehid}', NOW - timedelta(seconds=age) if age is not None else None,
                   mobile_number=f'AMB-{vehid}', zones=zones)


@pytest.mark.parametrize('site,expected', [(POBLADO, ['p', 'both']), (TALLER, ['t', 'both'])])
def test_site_exact_membership_with_single_acquisition(site, expected):
    client, clock = Mock(), Mock(return_value=NOW)
    client.get_vehicles.return_value = [report('outside', 1, ['ZONA 2 - POBLADO']),
                                       report('p', 20, [POBLADO]), report('t', 20, [TALLER]),
                                       report('both', 40, [TALLER, POBLADO]),
                                       report('wrong-case', 1, [POBLADO.lower()])]
    result = list_vehicles_at_site(client, site, now=clock)
    assert [entry.vehicle.vehid for entry in result.entries] == expected
    client.get_vehicles.assert_called_once_with()
    clock.assert_called_once_with()


def test_inventory_order_and_stale_retention():
    client = Mock()
    client.get_vehicles.return_value = [report('stale-old', 7200, [POBLADO]),
                                       report('fresh-old', 125, [POBLADO]),
                                       report('missing', None, [POBLADO]),
                                       report('stale-new', 786, [POBLADO]),
                                       report('fresh-new', 43, [POBLADO])]
    result = list_vehicles_at_site(client, POBLADO, now=lambda: NOW)
    assert [entry.vehicle.vehid for entry in result.entries] == [
        'fresh-new', 'fresh-old', 'stale-new', 'stale-old', 'missing',
    ]
    assert [entry.stale for entry in result.entries] == [False, False, True, True, None]
    assert [entry.report_age for entry in result.entries] == [43, 125, 786, 7200, None]


def test_missing_data_and_incomparable_timestamp_sort_last():
    client = Mock()
    incomplete = normalize_vehicle({'VEHID': 1, 'Zones': ' Z - {EMI_Medellin_Taller}'})
    incompatible = replace(incomplete, vehid='2', gps_timestamp=NOW.replace(tzinfo=timezone.utc))
    client.get_vehicles.return_value = [incompatible, incomplete, report('fresh', 1, [TALLER])]
    entries = list_vehicles_at_site(client, TALLER, now=lambda: NOW).entries
    assert [entry.vehicle.vehid for entry in entries] == ['fresh', '1', '2']
    assert entries[-1].report_age is None
    assert entries[-2].vehicle.mobile_number == entries[-2].vehicle.plate == ''


def test_inventory_ties_are_deterministic():
    client = Mock()
    a, b = report('a', 43, [POBLADO]), report('b', 43, [POBLADO])
    client.get_vehicles.side_effect = [[b, a], [a, b]]
    first = list_vehicles_at_site(client, POBLADO, now=lambda: NOW)
    second = list_vehicles_at_site(client, POBLADO, now=lambda: NOW)
    assert first.entries == second.entries


def test_invalid_site_rejected_before_acquisition():
    client = Mock()
    with pytest.raises(ValueError, match='Sede no permitida'):
        list_vehicles_at_site(client, 'ZONA 2 - POBLADO')
    client.get_vehicles.assert_not_called()


def test_both_queries_keep_provider_fleet_filter(monkeypatch):
    payload = """{'Rows':[
      {'VEHID':433909,'VEH_LCNS':'AMB-20','VEH_NAM':'PJU886',
       'fltName':'Ambulancias Medellin;44986;0','Zones':' Z - {EMI Medellin_Poblado}'},
      {'VEHID':2,'VEH_LCNS':'AMB-FOREIGN','VEH_NAM':'FOREIGN',
       'fltName':'Otra flota','Zones':' Z - {EMI Medellin_Poblado}'}]}"""
    load = Mock(return_value=payload)
    monkeypatch.setattr(WideTechClient, 'load_data_log', load)
    client = WideTechClient()
    assert [r.vehicle.vehid for r in list_vehicles_at_site(client, POBLADO, now=lambda: NOW).entries] == ['433909']
    assert get_vehicle_location(client, 'AMB-20', now=lambda: NOW).vehicle.plate == 'PJU886'
    with pytest.raises(VehicleNotFoundError):
        get_vehicle_location(client, 'AMB-FOREIGN', now=lambda: NOW)
    assert load.call_count == 3
