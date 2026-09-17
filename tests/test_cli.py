from datetime import datetime
from unittest.mock import Mock

import pytest

from gps_emi import cli
from gps_emi.models import Vehicle
from gps_emi.monitoring.arrival import DESTINATIONS
from gps_emi.notifications.console import ConsoleNotifier
from gps_emi.providers.widetech import WideTechError


def vehicle(inside=False):
    return Vehicle('1', 'AMB-106', datetime(2026, 9, 17, 10, 22, 31),
                   gps_fix=0, zones=[DESTINATIONS[1]] if inside else [])


def test_watch_notifies_once_and_finishes(capsys):
    client = Mock()
    client.get_vehicles.side_effect = [[vehicle()], [vehicle()], [vehicle(True)]]
    sleep = Mock()
    assert cli.watch(client, 'AMB-106', DESTINATIONS[1], 7, ConsoleNotifier(), sleep) == 0
    output = capsys.readouterr().out
    assert output.count('ARRIVAL_DETECTED') == 1
    assert 'Vigilancia completada.' in output
    assert 'GPSFix=0' in output
    assert '2026-09-17 10:22:31' in output
    assert client.get_vehicles.call_count == 3
    assert sleep.call_count == 2
    sleep.assert_called_with(7)


@pytest.mark.parametrize('rows', [[], [vehicle(), vehicle()]])
def test_missing_or_ambiguous_plate(rows):
    client, notifier, sleep = Mock(), Mock(), Mock()
    client.get_vehicles.return_value = rows
    assert cli.watch(client, 'AMB-106', DESTINATIONS[1], 30, notifier, sleep) == 1
    notifier.send_arrival.assert_not_called()
    sleep.assert_not_called()


def test_disappearing_vehicle_does_not_infer_transition():
    client, notifier = Mock(), Mock()
    client.get_vehicles.side_effect = [[vehicle(True)], []]
    assert cli.watch(client, 'AMB-106', DESTINATIONS[1], 30, notifier, Mock()) == 1
    notifier.send_arrival.assert_not_called()


@pytest.mark.parametrize('interval', ['0', '-1', 'nan', 'inf', 'abc'])
def test_invalid_interval(interval):
    with pytest.raises(SystemExit) as caught:
        cli.main(['--interval', interval])
    assert caught.value.code == 2


def test_interactive_selection(monkeypatch):
    answers = iter([' amb-106 ', '2'])
    monkeypatch.setattr('builtins.input', lambda prompt: next(answers))
    watch = Mock(return_value=0)
    monkeypatch.setattr(cli, 'watch', watch)
    assert cli.main([]) == 0
    assert watch.call_args.args[1:4] == ('AMB-106', DESTINATIONS[1], 30.0)


@pytest.mark.parametrize('answers', [[''], ['AMB-106', '3']])
def test_invalid_interactive_input(monkeypatch, answers):
    iterator = iter(answers)
    monkeypatch.setattr('builtins.input', lambda prompt: next(iterator))
    assert cli.main([]) == 1


@pytest.mark.parametrize('error,code', [(KeyboardInterrupt(), 130), (EOFError(), 130), (WideTechError('Sesión no disponible.'), 1)])
def test_clean_exit(monkeypatch, capsys, error, code):
    monkeypatch.setattr(cli, 'watch', Mock(side_effect=error))
    assert cli.main(['--plate', 'AMB-106', '--destination', DESTINATIONS[0]]) == code
    assert 'Traceback' not in capsys.readouterr().out
