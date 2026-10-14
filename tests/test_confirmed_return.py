"""New consent rule cannot be bypassed by phase-5 presence recovery."""
from unittest.mock import Mock
from dataclasses import replace

import pytest

from gps_emi.monitoring.watches import WatchManager
from gps_emi.monitoring.runner import WatchRunner
from gps_emi.sites import EMI_SITES
from gps_emi import cli
from snapshot_fakes import ScriptedSnapshots
from test_phase5_continuity import Clock, row


def test_inside_recovery_needs_exit_before_any_notification():
    clock = Clock()
    notify = Mock()
    manager = WatchManager(notify, now=clock.wall, monotonic=clock.mono)
    manager.create_watch('owner', row(0, EMI_SITES[:1]), 'target', require_exit=True)
    for second in (0, 301, 331, 361):
        clock.value = second
        manager.process_snapshot([row(second, EMI_SITES[:1])])
    notify.assert_not_called()
    # Neither stale nor duplicate exterior is evidence of an exit.
    clock.value = 700
    manager.process_snapshot([row(361)])
    manager.process_snapshot([row(362)])
    assert manager.get_active_watches('owner')[0].continuity.require_exit
    manager.process_snapshot([row(700)])
    assert not manager.get_active_watches('owner')[0].continuity.require_exit
    clock.value = 730
    manager.process_snapshot([row(730, EMI_SITES[1:])])
    notify.assert_called_once()
    assert notify.call_args.args[1].event_type == 'ARRIVAL_DETECTED'


@pytest.mark.parametrize('accept', [True, False])
def test_runner_confirmation_before_admission(accept):
    clock = Clock()
    transport = Mock()
    transport.get_vehicles.side_effect = [[row(0, EMI_SITES[:1])], [row(1)], [row(2, EMI_SITES[:1])]]
    source = ScriptedSnapshots(transport)
    confirm, notifier = Mock(return_value=accept), Mock()
    runner = WatchRunner(source, 'TEST-synthetic-a', None, notifier, now=clock.wall, confirm_inside=confirm)
    assert runner.run() == 0
    confirm.assert_called_once()
    assert notifier.send_arrival.call_count == int(accept)
    assert transport.get_vehicles.call_count == (3 if accept else 1)
    if not accept:
        assert runner.vehid is None and runner.continuity is None


def test_runner_confirmation_expires():
    transport = Mock(get_vehicles=Mock(return_value=[row(0, EMI_SITES[:1])]))
    source = ScriptedSnapshots(transport)
    def confirm(vehicle):
        source.time += 300
        return True
    runner = WatchRunner(source, 'TEST-synthetic-a', None, Mock(), confirm_inside=confirm)
    assert runner.run() == 0
    assert runner.vehid is None


def test_runner_revalidates_id_after_user_answers():
    transport = Mock(get_vehicles=Mock(side_effect=[[row(0, EMI_SITES[:1])], []]))
    source = ScriptedSnapshots(transport)
    def confirm(vehicle):
        pending = source.coordinator.request(refresh=True)
        source.advance()
        assert pending.done()
        return True
    runner = WatchRunner(source, 'TEST-synthetic-a', None, Mock(), confirm_inside=confirm)
    assert runner.run() == 1
    assert runner.failure_code == 'selected_unavailable'
    assert runner.vehid is None


@pytest.mark.parametrize('answer,accepted', [('s', True), ('sí', True), ('n', False), ('', False)])
def test_console_prompt_is_explicit(monkeypatch, answer, accepted, capsys):
    monkeypatch.setattr('builtins.input', lambda _: answer)
    assert cli._confirm_inside(row(0, EMI_SITES[:1])) is accepted
    assert 'Todavía no se ha iniciado' in capsys.readouterr().out
