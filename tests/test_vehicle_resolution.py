from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from gps_emi import cli
from gps_emi.models import Vehicle
from gps_emi.monitoring.arrival import DESTINATIONS
from gps_emi.notifications.console import ConsoleNotifier
from gps_emi.providers.widetech import WideTechClient, normalize_vehicle, parse
from gps_emi.resolution import AmbiguousVehicleError, VehicleNotFoundError, find_vehicle


@pytest.mark.parametrize('identifier', ['DEU942', 'AMB-20', 'deu942', 'amb-20', ' DEU942 ', ' amb-20 '])
def test_resolve_either_identifier_to_same_vehicle(identifier):
    vehicle = Vehicle('1', 'DEU942', mobile_number='AMB-20')
    assert find_vehicle([vehicle], identifier) is vehicle


@pytest.mark.parametrize('identifier', ['UNKNOWN', '', ' ', 'AMB', 'AMB20'])
def test_not_found(identifier):
    with pytest.raises(VehicleNotFoundError, match='No se encontró el móvil'):
        find_vehicle([Vehicle('1', 'DEU942', mobile_number='AMB-20')], identifier)


@pytest.mark.parametrize('other', [
    Vehicle('2', 'OTHER', mobile_number='AMB-20'),
    Vehicle('2', 'AMB-20', mobile_number='OTHER'),
])
def test_ambiguous_including_cross_field_collision(other):
    with pytest.raises(AmbiguousVehicleError, match='identificador es ambiguo'):
        find_vehicle([Vehicle('1', 'DEU942', mobile_number='AMB-20'), other], 'amb-20')


def test_same_vehicle_matching_both_fields_is_not_ambiguous():
    vehicle = Vehicle('1', 'AMB-20', mobile_number='AMB-20')
    assert find_vehicle([vehicle], 'AMB-20') is vehicle


def test_provider_fields_remain_separate_without_inferred_mapping():
    # No intercambiar campos ni inferir su semántica a partir del formato.
    row = parse("{'Rows':[{'VEHID':1,'VEH_LCNS':'Mobile code','VEH_NAM':'ABC123'}]}")[0]
    vehicle = normalize_vehicle(row)
    assert vehicle.plate == 'ABC123'
    assert vehicle.mobile_number == 'Mobile code'
    assert find_vehicle([vehicle], 'mobile CODE') is vehicle
    assert find_vehicle([vehicle], 'ABC123') is vehicle


@pytest.mark.parametrize('identifier', ['OUTSIDE-PLATE', 'OUTSIDE-MOBILE'])
def test_other_fleet_cannot_be_selected(monkeypatch, identifier, caplog):
    payload = """{'Rows':[
        {'VEHID':1,'VEH_LCNS':'AMB-20','VEH_NAM':'DEU942',
         'fltName':'Ambulancias Medellin;44986;0'},
        {'VEHID':2,'VEH_LCNS':'OUTSIDE-MOBILE','VEH_NAM':'OUTSIDE-PLATE',
         'fltName':'Otra flota'}]}"""
    monkeypatch.setattr(WideTechClient, 'load_data_log', lambda self: payload)
    client = WideTechClient()
    with pytest.raises(VehicleNotFoundError):
        find_vehicle(client.get_vehicles(), identifier)
    notifier = Mock()
    assert cli.watch(client, identifier, DESTINATIONS[0], 30, notifier, Mock()) == 1
    notifier.send_arrival.assert_not_called()
    assert 'No se encontró el móvil' in caplog.text


@pytest.mark.parametrize('plate', ['DEU942', ''])
@pytest.mark.parametrize('sequence', [[False, True], [True, True, False, True]])
def test_monitoring_by_mobile_keeps_transition_and_original_event(plate, sequence):
    vehicle = Vehicle('1', plate, mobile_number='AMB-20')
    observations = [replace(vehicle, zones=[DESTINATIONS[0]] if inside else [],
                            gps_timestamp=datetime(2026, 9, 17, 12, 30) + timedelta(seconds=index))
                    for index, inside in enumerate(sequence)]
    client, notifier, sleep = Mock(), Mock(), Mock()
    client.get_vehicles.side_effect = [[observation] for observation in observations]
    assert cli.watch(client, ' amb-20 ', DESTINATIONS[0], 30, notifier, sleep) == 0
    notifier.send_arrival.assert_called_once()
    event = notifier.send_arrival.call_args.args[0]
    assert event.vehicle is observations[-1]
    assert event.vehicle.plate == plate
    assert event.vehicle.mobile_number == 'AMB-20'
    assert client.get_vehicles.call_count == len(sequence)
    assert sleep.call_count == len(sequence) - 1


def test_ambiguous_cli_stops_before_creating_monitor(monkeypatch, caplog):
    client, notifier, monitor = Mock(), Mock(), Mock()
    client.get_vehicles.return_value = [Vehicle('1', 'DEU942', mobile_number='AMB-20'),
                                      Vehicle('2', 'OTHER', mobile_number='AMB-20')]
    monkeypatch.setattr('gps_emi.monitoring.runner.ArrivalMonitor', monitor)
    assert cli.watch(client, 'AMB-20', DESTINATIONS[0], 30, notifier, Mock()) == 1
    assert 'identificador es ambiguo' in caplog.text
    monitor.assert_not_called()
    notifier.send_arrival.assert_not_called()


@pytest.mark.parametrize('flag', ['--identifier', '--plate'])
def test_cli_argument_compatibility(monkeypatch, flag):
    watch = Mock(return_value=0)
    monkeypatch.setattr(cli, 'watch', watch)
    assert cli.main([flag, ' amb-20 ', '--destination', DESTINATIONS[0]]) == 0
    assert watch.call_args.args[1] == 'AMB-20'


def test_prompt_and_notification_for_mobile_without_plate(monkeypatch, caplog):
    from gps_emi.models import ArrivalEvent

    prompts = []
    def input_identifier(prompt):
        prompts.append(prompt)
        return 'AMB-20'
    monkeypatch.setattr('builtins.input', input_identifier)
    monkeypatch.setattr(cli, 'watch', Mock(return_value=0))
    assert cli.main(['--destination', DESTINATIONS[0]]) == 0
    assert prompts == ['Placa o número de móvil: ']
    ConsoleNotifier().send_arrival(ArrivalEvent(Vehicle('1', '', mobile_number='AMB-20'), DESTINATIONS[0]))
    assert 'AMB-20 llegó a' in caplog.text


def test_observed_mobile_and_plate_resolve_same_vehicle(monkeypatch, observed_amb20_payload):
    monkeypatch.setattr(WideTechClient, 'load_data_log', lambda self: observed_amb20_payload)
    vehicles = WideTechClient().get_vehicles()
    by_number = find_vehicle(vehicles, 'AMB-20')
    by_plate = find_vehicle(vehicles, 'PJU886')
    assert by_number.vehid == by_plate.vehid == '433909'
    assert by_number is by_plate is vehicles[0]


@pytest.mark.parametrize('identifier', [' amb-20 ', ' pju886 '])
def test_observed_vehicle_monitor_and_notification(identifier, observed_amb20_payload, caplog):
    vehicle = normalize_vehicle(parse(observed_amb20_payload)[0])
    # Zones y timestamps se simulan para la transición; no son datos observados.
    vehicle = replace(vehicle, gps_timestamp=datetime(2026, 9, 17, 12, 30))
    inside = replace(vehicle, zones=[DESTINATIONS[0]], gps_timestamp=datetime(2026, 9, 17, 12, 31))
    client, notifier = Mock(), Mock()
    client.get_vehicles.side_effect = [[vehicle], [inside]]
    assert cli.watch(client, identifier, DESTINATIONS[0], 30, notifier, Mock()) == 0
    notifier.send_arrival.assert_called_once()
    event = notifier.send_arrival.call_args.args[0]
    assert event.vehicle is inside
    assert event.vehicle.plate == 'PJU886'
    assert event.vehicle.mobile_number == 'AMB-20'
    ConsoleNotifier().send_arrival(event)
    assert 'PJU886 llegó a' in caplog.text
