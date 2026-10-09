from snapshot_fakes import ScriptedSnapshots
from dataclasses import replace
from datetime import datetime, timedelta
import logging
from unittest.mock import Mock
import uuid

import pytest

from gps_emi.config import WatchConfig
from gps_emi.errors import SessionExpiredError, TransientAcquisitionError, TransientHTTPError
from gps_emi.models import Vehicle
from gps_emi.monitoring.arrival import ArrivalMonitor, DESTINATIONS, MonitorState
from gps_emi.monitoring.runner import WatchRunner

BASE = datetime(2026, 9, 17, 12, 30)
NOW = BASE + timedelta(minutes=5)
DESTINATION = DESTINATIONS[0]


def report(seconds=0, inside=False, **changes):
    vehicle = Vehicle('433909', 'PJU886', gps_timestamp=BASE + timedelta(seconds=seconds),
                      gps_fix=1, mobile_number='AMB-20', zones=[DESTINATION] if inside else [])
    return replace(vehicle, **changes)


def make_runner(sequence, **kwargs):
    client, notifier, sleep = Mock(), Mock(), Mock()
    client.get_vehicles.side_effect = [
        [item] if isinstance(item, Vehicle) else item for item in sequence
    ] + [SessionExpiredError()]
    runner = WatchRunner(ScriptedSnapshots(client, interval=(kwargs.get("config") or WatchConfig()).polling_interval), 'AMB-20', DESTINATION, notifier,
                         sleep=sleep, now=lambda: NOW, **kwargs)
    return runner


@pytest.fixture
def observations(monkeypatch):
    observed = []
    original = ArrivalMonitor.observe
    def spy(self, vehicle):
        observed.append(vehicle)
        return original(self, vehicle)
    monkeypatch.setattr(ArrivalMonitor, 'observe', spy)
    return observed


@pytest.mark.parametrize('initial_inside,final_inside,expected_events', [
    (False, False, 0), (False, True, 1), (True, True, 0),
])
def test_errors_preserve_state(initial_inside, final_inside, expected_events, observations):
    runner = make_runner([report(0, initial_inside), TransientAcquisitionError(),
                          report(60, final_inside)])
    assert runner.run() == (0 if expected_events else 1)
    assert runner.notifier.send_arrival.call_count == expected_events
    assert [v.gps_timestamp for v in observations] == [BASE, BASE + timedelta(minutes=1)]
    expected_state = (MonitorState.ARRIVAL_DETECTED if expected_events else
                      MonitorState.INSIDE if final_inside else MonitorState.OUTSIDE)
    assert runner.monitor.state == expected_state
    runner.sleep.assert_not_called()


def test_network_and_http_errors_never_observe(observations):
    runner = make_runner([report(), TransientAcquisitionError(), TransientHTTPError(503),
                          report(60), report(120, True)])
    assert runner.run() == 0
    assert len(observations) == 3
    runner.notifier.send_arrival.assert_called_once()
    assert runner.notifier.send_arrival.call_args.args[0].vehicle.gps_timestamp == BASE + timedelta(minutes=2)


def test_backoff_cap_recovery_counter_and_normal_polling(caplog):
    runner = make_runner([*[TransientAcquisitionError() for _ in range(5)],
                          report(), TransientAcquisitionError(), report(60)])
    assert runner.run() == 1
    runner.sleep.assert_not_called()
    recovery = [record for record in caplog.records if 'Adquisición recuperada' in record.message]
    assert len(recovery) == 2
    assert all(record.levelno == logging.INFO for record in recovery)


def test_configurable_backoff_and_interval():
    runner = make_runner([TransientAcquisitionError(), TransientAcquisitionError(),
                          TransientAcquisitionError(), report()],
                         config=WatchConfig(polling_interval=11, initial_backoff=2, max_backoff=3))
    assert runner.run() == 1
    runner.sleep.assert_not_called()


def test_session_expired_terminates_without_retry(caplog):
    runner = make_runner([SessionExpiredError()])
    assert runner.run() == 1
    runner.sleep.assert_not_called()
    runner.notifier.send_arrival.assert_not_called()
    assert runner.client.transport.get_vehicles.call_count == 1
    assert runner.monitor is None
    assert runner.client.coordinator.blocked


def test_stale_and_gpsfix_zero_do_not_discard_new_observation(caplog):
    runner = make_runner([report(-120, gps_fix=0), report(-60, True, gps_fix='0')])
    assert runner.run() == 0
    runner.notifier.send_arrival.assert_called_once()
    assert any(record.levelno == logging.WARNING and 'STALE' in record.message for record in caplog.records)
    assert 'GPSFix=0' in caplog.text
    assert 'report_age=360 s' in caplog.text


@pytest.mark.parametrize('age,expected', [(300, False), (301, True)])
def test_stale_threshold_is_strict(age, expected, caplog):
    runner = make_runner([report(300 - age)])
    runner.run()
    assert ('STALE' in caplog.text) == expected
    assert runner.monitor.state == MonitorState.OUTSIDE


def test_configurable_stale_warning(caplog):
    runner = make_runner([report(299)], config=WatchConfig(stale_warning_seconds=0))
    runner.run()
    assert 'STALE' in caplog.text


def test_duplicate_can_become_stale_without_reprocessing_or_repeated_warning(caplog, observations):
    runner = make_runner([report(), report(), report(), report()])
    runner.now = Mock(side_effect=[BASE, NOW, NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)])
    runner.run()
    assert len(observations) == 1
    assert sum('STALE' in r.message for r in caplog.records) == 1
    assert sum('OUTSIDE |' in r.message for r in caplog.records) == 1


@pytest.mark.parametrize('sequence', [
    [report(), report(-60, True), report(60, True)],
    [report(), report(0, True), report(60, True)],
    [report(), report(), report(), report(60, True)],
])
def test_old_or_duplicate_reports_cannot_trigger_arrival(sequence, observations):
    runner = make_runner(sequence)
    assert runner.run() == 0
    assert [v.gps_timestamp for v in observations] == [BASE, BASE + timedelta(minutes=1)]
    runner.notifier.send_arrival.assert_called_once()
    assert runner.validator.last_processed_gps_timestamp == BASE + timedelta(minutes=1)
    assert runner.client.transport.get_vehicles.call_count == len(sequence)


def test_out_of_order_warning_and_duplicate_debug(caplog):
    caplog.set_level(logging.DEBUG, logger='gps_emi')
    runner = make_runner([report(), report(-1, True), report(0, True)])
    runner.run()
    assert any(r.levelno == logging.WARNING and 'OUT_OF_ORDER' in r.message for r in caplog.records)
    assert any(r.levelno == logging.DEBUG and 'DUPLICATE' in r.message for r in caplog.records)
    runner.notifier.send_arrival.assert_not_called()
    assert runner.monitor.state == MonitorState.OUTSIDE


@pytest.mark.parametrize('initial_inside,expected_events', [(False, 1), (True, 0)])
def test_temporarily_missing_vehicle_reappears(initial_inside, expected_events, observations, caplog):
    runner = make_runner([report(0, initial_inside), [], [], report(60, True)])
    assert runner.run() == (0 if expected_events else 1)
    assert len(observations) == 2
    assert runner.notifier.send_arrival.call_count == expected_events
    runner.sleep.assert_not_called()
    assert 'temporalmente ausente' in caplog.text
    assert 'temporalmente ausente; estado conservado' in caplog.text


def test_tracks_vehid_despite_identifier_changes_and_reuse():
    runner = make_runner([report(), [report(60, True, vehid='other')],
                          [report(120, True, plate='NEW123', mobile_number='AMB-NEW'),
                           report(120, True, vehid='other')]])
    assert runner.run() == 0
    event = runner.notifier.send_arrival.call_args.args[0]
    assert event.vehicle.vehid == '433909'
    assert event.vehicle.plate == 'NEW123'
    assert event.vehicle.mobile_number == 'AMB-NEW'
    runner.notifier.send_arrival.assert_called_once()


def test_missing_timestamp_never_establishes_or_changes_state(caplog, observations):
    runner = make_runner([report(0, True, gps_timestamp=None), report(),
                          report(0, True, gps_timestamp=None), report(60, True)])
    assert runner.run() == 0
    assert [v.gps_timestamp for v in observations] == [BASE, BASE + timedelta(minutes=1)]
    assert 'MISSING_TIMESTAMP' in caplog.text


@pytest.mark.parametrize('sequence', [
    [report(vehid='')],
    [[report(), report(plate='OTHER', mobile_number='OTHER')]],
    [report(), [report(60), report(60)]],
])
def test_missing_or_ambiguous_vehid_is_fatal(sequence):
    runner = make_runner(sequence)
    assert runner.run() == 1
    runner.notifier.send_arrival.assert_not_called()


@pytest.mark.parametrize('stage', ['request', 'polling', 'backoff'])
def test_ctrl_c_at_each_stage(stage, caplog):
    runner = make_runner([KeyboardInterrupt()] if stage == 'request' else
                         [TransientAcquisitionError()] if stage == 'backoff' else [report()])
    if stage != 'request':
        runner.client.transport.get_vehicles.side_effect = ([TransientAcquisitionError(), KeyboardInterrupt()] if stage == 'backoff' else [[report()], KeyboardInterrupt()])
    assert runner.run() == 130
    assert 'Vigilancia cancelada.' in caplog.text
    assert 'Traceback' not in caplog.text
    runner.notifier.send_arrival.assert_not_called()


@pytest.mark.parametrize('error_type', [TransientAcquisitionError, SessionExpiredError, RuntimeError])
def test_logs_never_include_exception_details(error_type, caplog):
    marker = uuid.uuid4().hex
    runner = make_runner([report(), error_type(marker), report(60, True)])
    runner.run()
    assert marker not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_completed_runner_never_notifies_twice():
    runner = make_runner([report(), report(60, True)])
    assert runner.run() == runner.run() == 0
    runner.notifier.send_arrival.assert_called_once()
    assert runner.client.transport.get_vehicles.call_count == 2


def test_notification_failure_is_not_retried(caplog):
    runner = make_runner([report(), report(60, True)])
    marker = uuid.uuid4().hex
    runner.notifier.send_arrival.side_effect = RuntimeError(marker)
    assert runner.run() == runner.run() == 1
    runner.notifier.send_arrival.assert_called_once()
    assert marker not in caplog.text


def test_future_timestamp_warns_but_is_not_automatically_discarded(caplog, observations):
    runner = make_runner([report(360)])
    runner.run()
    assert 'posterior al reloj' in caplog.text
    assert len(observations) == 1
    assert runner.validator.last_processed_gps_timestamp == BASE + timedelta(minutes=6)


def test_recovery_on_duplicate_restores_interval_and_resets_backoff():
    runner = make_runner([report(), TransientAcquisitionError(), report(),
                          TransientAcquisitionError(), report(60, True)])
    assert runner.run() == 0
    runner.sleep.assert_not_called()
    assert runner.client.coordinator.backoff == 0
