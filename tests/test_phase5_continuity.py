"""Offline phase 5: injected clocks, synthetic identities, no operational data."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from gps_emi.acquisition import Coordinator, SnapshotSource, SnapshotUnavailable
from gps_emi.config import WatchConfig
from gps_emi.models import Vehicle, PresenceEvent
from gps_emi.monitoring.arrival import ArrivalMonitor, MonitorState
from gps_emi.monitoring.runner import WatchRunner
from gps_emi.monitoring.watches import WatchManager, WatchStatus
from gps_emi.monitoring.fleet_polling import FleetPolling
from gps_emi.providers.widetech_official import OfficialAcquisitionError, ErrorKind
from gps_emi.sites import EMI_SITES
from gps_emi.whatsapp.formatting import format_arrival
from gps_emi.whatsapp.notifier import WhatsAppNotifier
from gps_emi.whatsapp.delivery import Messenger, ServiceWindow
from gps_emi.notifications.console import ConsoleNotifier

BASE = datetime(2026, 10, 11, 12)


class Clock:
    value = 0.0

    def mono(self):
        return self.value

    def wall(self):
        return BASE + timedelta(seconds=self.value)

    def utc(self):
        return (self.wall() + timedelta(hours=5)).replace(tzinfo=timezone.utc)


def row(seconds=0, sites=(), vid='synthetic-a', **changes):
    return replace(Vehicle(vid, 'TEST-'+vid, BASE+timedelta(seconds=seconds),
                           mobile_number='TEST-MOBILE', zones=list(sites)), **changes)


def rig(limit=43200):
    clock = Clock()
    transport = Mock(acquire=Mock(return_value=(row(),)))
    coordinator = Coordinator(transport, monotonic=clock.mono, utcnow=clock.utc)
    coordinator.demand('test', True)
    notify = Mock(return_value=True)
    manager = WatchManager(notify, WatchConfig(inactivity_seconds=limit), now=clock.wall,
                           monotonic=clock.mono, timing=coordinator.watch_timing)
    watch, _ = manager.create_watch('owner', row(), 'target')
    return clock, coordinator, manager, watch, notify


def state(manager, watch):
    return manager.get_watch(watch.owner_id, watch.watch_id)


@pytest.mark.parametrize('age,events', [(299, 1), (300, 1), (300.001, 0)])
def test_exact_stale_boundary_independent_of_warning_and_gpsfix(age, events):
    clock, _, manager, watch, notify = rig()
    manager.process_snapshot([row(-300, gps_fix=0)])
    clock.value = 1
    manager.process_snapshot([row(1-age, EMI_SITES[:1], gps_fix=0)])
    assert notify.call_count == events
    if not events:
        assert state(manager, watch).continuity.activity_at == 0


@pytest.mark.parametrize('gap,kind', [(299.999, 'ARRIVAL_DETECTED'), (300, None), (301, None)])
def test_interruption_boundary(gap, kind):
    clock, _, manager, watch, notify = rig()
    manager.process_snapshot([row()])
    clock.value = gap
    manager.process_snapshot([row(gap, EMI_SITES[:1])])
    assert (notify.call_args.args[1].event_type if notify.called else None) == kind
    assert state(manager, watch).continuity.interrupted == (kind is None)


def test_initial_inside_not_arrival_and_stale_initial_does_not_backdate_expiry():
    clock, _, manager, watch, notify = rig()
    manager.process_snapshot([row(-90000, EMI_SITES[:1])])
    assert state(manager, watch).monitor.state == MonitorState.INITIAL
    manager.process_snapshot([row(0, EMI_SITES[:1])])
    notify.assert_not_called()
    clock.value = 43200
    manager.tick()
    assert state(manager, watch).status == WatchStatus.ACTIVE
    clock.value += .001
    manager.process_snapshot([row(clock.value, EMI_SITES[:1])])
    assert state(manager, watch).status == WatchStatus.EXPIRED
    assert state(manager, watch).failure_code == 'inactivity'
    notify.assert_not_called()


def test_duplicates_out_of_order_missing_do_not_reset_activity_or_recovery():
    clock, _, manager, watch, notify = rig()
    manager.process_snapshot([row()])
    clock.value = 300
    manager.tick()
    for vehicle in [row(0, EMI_SITES[:1]), row(-1), row(gps_timestamp=None)]:
        manager.process_snapshot([vehicle])
    manager.process_snapshot([])
    manager.process_snapshot([row(300), row(300)])
    assert state(manager, watch).continuity.activity_at == 0
    for seconds in (301, 302):
        clock.value = seconds
        manager.process_snapshot([row(seconds, EMI_SITES[:1])])
        manager.process_snapshot([row(seconds, EMI_SITES[:1])])
    assert state(manager, watch).continuity.recovery_count == 2
    assert not notify.called
    clock.value = 303
    manager.process_snapshot([row(303, EMI_SITES[:1], plate='RENAMED')])
    manager.process_snapshot([row(304, EMI_SITES[:1])])
    notify.assert_called_once()
    event = notify.call_args.args[1]
    assert event.event_type == 'PRESENCE_CONFIRMED' and event.vehicle.plate == 'RENAMED'
    assert state(manager, watch).status == WatchStatus.COMPLETED


def test_recovery_site_change_ambiguous_sites_and_second_interruption_reset_sequence():
    clock, _, manager, watch, notify = rig()
    manager.process_snapshot([row()])
    for seconds, sites, expected in [(300, EMI_SITES[:1], 1), (301, EMI_SITES[1:], 1),
                                      (302, EMI_SITES, 0), (303, EMI_SITES[:1], 1),
                                      (603, EMI_SITES[:1], 1), (604, EMI_SITES[:1], 2),
                                      (605, EMI_SITES[:1], 3)]:
        clock.value = seconds
        manager.process_snapshot([row(seconds, sites)])
        assert state(manager, watch).continuity.recovery_count == expected
    notify.assert_called_once()


def test_fresh_exterior_recovers_normal_monitor_then_arrival():
    clock, _, manager, watch, notify = rig()
    manager.process_snapshot([row()])
    clock.value = 300
    manager.process_snapshot([row(300, EMI_SITES[:1])])
    clock.value = 301
    manager.process_snapshot([row(301)])
    assert not state(manager, watch).continuity.interrupted
    clock.value = 302
    manager.process_snapshot([row(302, EMI_SITES[1:])])
    assert notify.call_args.args[1].event_type == 'ARRIVAL_DETECTED'


@pytest.mark.parametrize('kind', [ErrorKind.NETWORK, ErrorKind.TIMEOUT, ErrorKind.HTTP,
                                 ErrorKind.PAYLOAD, ErrorKind.EMPTY, ErrorKind.SOAP])
def test_pause_starts_first_failed_attempt_without_backdating(kind):
    clock, central, manager, watch, notify = rig(limit=100)
    manager.process_snapshot([row()])
    clock.value = 90
    central.source.acquire.side_effect = OfficialAcquisitionError(kind)
    assert not central.tick()
    clock.value = 10000
    manager.tick()
    assert state(manager, watch).status == WatchStatus.ACTIVE
    assert state(manager, watch).continuity.interrupted
    assert central.watch_timing(0) == (90, False)
    assert not central.tick()  # A repeated failure cannot start another pause.
    assert central.watch_timing(0)[0] == 90
    clock.value = central.next_start
    central.source.acquire.side_effect = None
    assert central.tick()
    manager.process_snapshot([row()])  # Whole fleet repeats GPS: resumes inactivity.
    assert state(manager, watch).continuity.activity_at == 0
    clock.value += 10
    manager.tick()
    assert state(manager, watch).status == WatchStatus.ACTIVE
    clock.value += .001
    manager.tick()
    assert state(manager, watch).status == WatchStatus.EXPIRED
    notify.assert_not_called()


def test_multiple_pause_cycles_and_watch_created_during_pause():
    clock, central, manager, watch, _ = rig()
    clock.value = 100
    central.source.acquire.side_effect = OfficialAcquisitionError(ErrorKind.NETWORK)
    central.tick()
    clock.value = 150
    second, _ = manager.create_watch('other-owner', row(vid='synthetic-b'), 'target-b')
    clock.value = 200
    central.source.acquire.side_effect = None
    central.tick()
    clock.value = 250
    central.source.acquire.side_effect = OfficialAcquisitionError(ErrorKind.TIMEOUT)
    central.tick()
    clock.value = 400
    central.source.acquire.side_effect = None
    central.tick()
    assert central.watch_timing(0)[0] == 150
    assert central.watch_timing(second.continuity.activity_at)[0] == 50
    clock.value = 401
    manager.process_snapshot([row(401, vid='synthetic-b')])
    assert state(manager, second).continuity.activity_at == 401
    assert state(manager, watch).continuity.activity_at == 0


def test_local_persistence_pause_keeps_category_and_last_publication(tmp_path):
    from test_phase3_catalog import rig as catalog_rig, batch, record
    central, source, clock, store = catalog_rig(tmp_path, batch(record()), batch(record()), batch(record()))
    assert central.tick()
    previous = central.peek()
    apply = store.apply
    store.apply = Mock(side_effect=RuntimeError('synthetic failure'))
    clock.value = 30
    assert not central.tick()
    assert central.last_error == ('persistence', None)
    assert central.peek() is previous
    clock.value = 10000
    assert central.watch_timing(0)[0] == 30
    store.apply = apply
    assert central.tick()
    clock.value += 1
    assert central.watch_timing(0)[0] == 31


@pytest.mark.parametrize('kind', [ErrorKind.AUTHENTICATION, ErrorKind.AUTHORIZATION,
                                 ErrorKind.CONFIGURATION, ErrorKind.FUNCTIONAL])
def test_terminal_error_wins_over_pause_and_expiry(kind):
    clock, central, manager, watch, notify = rig(limit=10)
    fleet = FleetPolling(lambda: SnapshotSource(central), manager, autostart=False)
    central.source.acquire.side_effect = OfficialAcquisitionError(ErrorKind.TIMEOUT)
    central.tick()
    clock.value = 100000
    central.source.acquire.side_effect = OfficialAcquisitionError(kind)
    central.tick()
    fleet.cycle()
    current = state(manager, watch)
    assert current.status == WatchStatus.FAILED and current.failure_code == 'acquisition'
    notify.assert_not_called()


def test_timer_cycles_do_not_acquire_or_redeliver_collector():
    clock, central, manager, watch, notify = rig(limit=400)
    collector = Mock(active=True)
    fleet = FleetPolling(lambda: SnapshotSource(central), manager, autostart=False, collector=collector)
    central.tick()
    fleet.cycle()
    for instant in (100, 300, 400, 401):
        clock.value = instant
        fleet.cycle()
    assert state(manager, watch).status == WatchStatus.EXPIRED
    assert central.source.acquire.call_count == 1
    collector.submit.assert_called_once()


@pytest.mark.parametrize('terminal', ['cancel', 'fleet', 'expiry'])
def test_terminal_serialized_before_recovery_prevents_late_event(terminal):
    clock, _, manager, watch, notify = rig(limit=301)
    manager.process_snapshot([row()])
    for t in (300, 301):
        clock.value = t
        manager.process_snapshot([row(t, EMI_SITES[:1])])
    done = Event()
    def terminate():
        if terminal == 'cancel':
            manager.cancel_watch('owner', watch.watch_id)
        elif terminal == 'fleet':
            manager.reconcile_identities([Mock(vehicle_id=watch.vehicle_id, plate='NEW',
                                              mobile_number='NEW', fleet_name='Ambulancias Cali')])
        else:
            clock.value = 603
            manager.tick()
        done.set()
    def late():
        assert done.wait(2)
        manager.process_snapshot([row(clock.value, EMI_SITES[:1])])
    with ThreadPoolExecutor(2) as executor:
        futures = [executor.submit(terminate), executor.submit(late)]
        for f in futures:
            f.result(timeout=3)
    notify.assert_not_called()
    assert state(manager, watch).status != WatchStatus.ACTIVE


def test_recovery_reserves_once_before_concurrent_cancel_and_late_snapshot():
    clock, _, manager, watch, notify = rig()
    entered, release = Event(), Event()
    def delivery(*args):
        entered.set()
        assert release.wait(2)
        return True
    notify.side_effect = delivery
    manager.process_snapshot([row()])
    for t in (300, 301):
        clock.value = t
        manager.process_snapshot([row(t, EMI_SITES[:1])])
    clock.value = 302
    worker = Thread(target=lambda: manager.process_snapshot([row(302, EMI_SITES[:1])]))
    worker.start()
    try:
        assert entered.wait(2)
        assert manager.cancel_watch('owner', watch.watch_id) is None
        manager.process_snapshot([row(303, EMI_SITES[:1])])
        manager.tick()
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()
    notify.assert_called_once()


def test_cli_and_manager_same_sequence_and_expiry():
    clock, central, manager, watch, notify = rig()
    cli_notify = Mock()
    runner = WatchRunner(SnapshotSource(central), row().plate, None, cli_notify,
                         now=clock.wall)
    runner.vehid, runner.monitor = row().vehid, ArrivalMonitor(row().plate)
    for t, sites in [(0, ()), (300, EMI_SITES[:1]), (301, EMI_SITES[:1]),
                      (301, EMI_SITES[:1]), (302, EMI_SITES[:1])]:
        clock.value = t
        vehicle = row(t, sites)
        manager.process_snapshot([vehicle])
        runner._process(vehicle)
    assert cli_notify.send_arrival.call_args.args[0] == notify.call_args.args[1]
    assert runner.continuity == state(manager, watch).continuity
    assert WatchManager(Mock()).list_watches('owner') == []  # Restart never restores.


def test_presence_text_and_closed_window_never_reuse_arrival_template(caplog):
    event = PresenceEvent(row(0, EMI_SITES[:1]), EMI_SITES[0])
    text = format_arrival(event)
    assert 'Presencia confirmada' in text and 'No se conoce la hora de llegada' in text
    assert 'Llegada de ambulancia detectada' not in text
    ConsoleNotifier().send_arrival(event)
    assert 'No se conoce la hora de llegada' in caplog.text
    client = Mock()
    windows = ServiceWindow(now=lambda: 100)
    notifier = WhatsAppNotifier('target', Messenger(client, windows), Mock(arrival_mode='template'))
    notifier.send_arrival(event)
    notifier.send_arrival(event)
    assert notifier.delivery_error == 'service_window_closed' and not notifier.accepted
    client.send_template.assert_not_called()
    client.send_text.assert_not_called()


def test_inflight_failure_pause_starts_at_attempt_not_completion():
    clock, central, manager, watch, _ = rig(limit=100)
    entered, release = Event(), Event()
    def acquire():
        entered.set()
        assert release.wait(2)
        raise OfficialAcquisitionError(ErrorKind.TIMEOUT)
    central.source.acquire.side_effect = acquire
    clock.value = 90
    worker = Thread(target=central.tick)
    worker.start()
    try:
        assert entered.wait(2)
        clock.value = 1000
        manager.tick()
        assert state(manager, watch).status == WatchStatus.ACTIVE
    finally:
        release.set()
        worker.join(2)
    manager.tick()
    assert central.watch_timing(0) == (90, False)
    assert state(manager, watch).status == WatchStatus.ACTIVE


def test_successful_inflight_does_not_rescue_an_already_expired_watch():
    clock, central, manager, watch, notify = rig(limit=100)
    manager.process_snapshot([row()])
    def slow_success():
        clock.value = 110
        manager.tick()  # Decision deferred while the outcome is unknown.
        assert state(manager, watch).status == WatchStatus.ACTIVE
        return (row(110, EMI_SITES[:1]),)
    central.source.acquire.side_effect = slow_success
    clock.value = 90
    central.tick()
    manager.process_snapshot(SnapshotSource(central).get_vehicles(purpose='watch'))
    assert state(manager, watch).status == WatchStatus.EXPIRED
    notify.assert_not_called()


def test_pause_ends_at_publication_after_local_persistence(tmp_path):
    from test_phase3_catalog import rig as catalog_rig, batch, record
    central, source, clock, store = catalog_rig(tmp_path,
        OfficialAcquisitionError(ErrorKind.TIMEOUT), batch(record()))
    central.tick()
    original = store.apply
    def slow_store(snapshot):
        clock.value += 20
        return original(snapshot)
    store.apply = slow_store
    clock.value = 30
    central.tick()
    assert central.published_at == 50
    assert central.watch_timing(0) == (0, False)
    clock.value = 51
    assert central.watch_timing(0)[0] == 1


def test_runner_expires_from_wait_heartbeat_without_publication(monkeypatch):
    from concurrent.futures import TimeoutError
    clock, central, _, _, _ = rig(limit=100)
    central.tick()
    source = SnapshotSource(central)
    runner = WatchRunner(source, row().plate, None, Mock(),
                         WatchConfig(inactivity_seconds=100), now=clock.wall)
    request = central.request
    pending = Mock()
    def timed_result(**kwargs):
        clock.value = 101
        raise TimeoutError()
    pending.result.side_effect = timed_result
    monkeypatch.setattr(central, 'request', lambda **kw: pending if kw.get('refresh') else request(**kw))
    assert runner.run() == 1
    assert runner.failure_code == 'inactivity'
    pending.cancel.assert_called_once()
    assert central.source.acquire.call_count == 1
    runner.notifier.send_arrival.assert_not_called()


def test_runner_keeps_watch_after_wait_deadline_during_pause(monkeypatch):
    clock, central, _, _, _ = rig()
    central.tick()
    source = SnapshotSource(central)
    stop = Event()
    runner = WatchRunner(source, row().plate, None, Mock(), now=clock.wall, stop_event=stop)
    calls = []
    def wait(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            return central.peek()
        if len(calls) == 2:
            clock.value = 30
            central.source.acquire.side_effect = OfficialAcquisitionError(ErrorKind.TIMEOUT)
            central.tick()
            clock.value = 100000
            kwargs['on_tick']()
            raise SnapshotUnavailable()
        stop.set()
        kwargs['on_tick']()
    monkeypatch.setattr(source, 'wait', wait)
    assert runner.run() == 130
    assert len(calls) == 3 and runner.failure_code is None
    assert runner.continuity.interrupted


def test_fleet_worker_wakes_for_watches_without_pending_or_publications():
    clock, central, manager, watch, _ = rig()
    fleet = FleetPolling(lambda: SnapshotSource(central), manager, autostart=False)
    waits = []
    def wait(timeout=None):
        waits.append(timeout)
        fleet.stop_event.set()
    fleet.condition.wait = wait
    fleet._run()
    assert waits == [0.2]
    central.source.acquire.assert_not_called()


def test_whatsapp_adapter_recovery_and_cli_event_have_same_semantics():
    from gps_emi.whatsapp.service import WatchManager as WhatsAppWatches
    clock, central, _, _, _ = rig()
    messenger = Mock()
    adapter = WhatsAppWatches(lambda: SnapshotSource(central), messenger,
                              Mock(arrival_mode='text'), autostart=False)
    adapter.manager.now = clock.wall
    adapter.start('owner', row().plate)
    notifier = Mock()
    runner = WatchRunner(SnapshotSource(central), row().plate, None, notifier, now=clock.wall)
    runner.vehid, runner.monitor = row().vehid, ArrivalMonitor(row().plate)
    for t, sites in [(0, ()), (300, EMI_SITES[:1]), (330, EMI_SITES[:1]), (360, EMI_SITES[:1])]:
        clock.value = t
        vehicle = row(t, sites)
        central.source.acquire.return_value = (vehicle,)
        central.tick()
        adapter.polling.cycle()
        runner._process(vehicle)
    event = notifier.send_arrival.call_args.args[0]
    assert event.event_type == 'PRESENCE_CONFIRMED'
    assert messenger.reply.call_args.args == ('owner', format_arrival(event))
    assert len([c for c in messenger.reply.call_args_list if 'Presencia confirmada' in c.args[1]]) == 1
    assert not adapter.list_active('owner')


def test_retained_official_position_never_resets_watch_activity(tmp_path):
    from test_phase3_catalog import rig as catalog_rig, batch, record
    central, source, clock, _ = catalog_rig(tmp_path, batch(record()), batch(record(FechaGPS='bad')))
    manager = WatchManager(Mock(), now=lambda: datetime(2025, 12, 31, 19))
    fleet = FleetPolling(lambda: source, manager, autostart=False)
    fleet.request_watch('owner', 'TEST-A', 'target')
    central.tick(); fleet.cycle()
    watch = manager.list_watches('owner')[0]
    clock.value = 300
    central.tick(); fleet.cycle()
    assert central.peek().operational[0].retained_reason == 'row_quality'
    current = state(manager, watch)
    assert current.continuity.activity_at == 0 and current.continuity.interrupted
    assert current.status == WatchStatus.ACTIVE


@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf')])
def test_invalid_inactivity_configuration(value):
    with pytest.raises(ValueError):
        WatchConfig(inactivity_seconds=value)


def test_absent_initial_timestamp_and_wall_clock_jump_do_not_change_duration():
    clock, _, manager, watch, _ = rig(limit=100)
    manager.process_snapshot([row(gps_timestamp=None)])
    manager.now = lambda: BASE + timedelta(days=365)
    clock.value = 100
    manager.tick()
    assert state(manager, watch).status == WatchStatus.ACTIVE
    clock.value += .001
    manager.tick()
    assert state(manager, watch).status == WatchStatus.EXPIRED


def test_watch_pause_does_not_extend_campaign(tmp_path):
    from gps_emi.analysis.sessions import SessionStore
    clock, central, manager, watch, _ = rig(limit=100)
    store = SessionStore(tmp_path/'campaign.db')
    store.start_session(100, now=clock.utc())
    clock.value = 30
    central.source.acquire.side_effect = OfficialAcquisitionError(ErrorKind.TIMEOUT)
    central.tick()
    clock.value = 1000
    manager.tick()
    assert state(manager, watch).status == WatchStatus.ACTIVE
    assert store.status(now=clock.utc())['status'] == 'COMPLETED'


def test_terminal_publication_invalidates_queued_recovery_before_next_cycle():
    clock, central, manager, watch, notify = rig()
    terminal = Mock()
    fleet = FleetPolling(lambda: SnapshotSource(central), manager, autostart=False, on_terminal=terminal)
    manager.process_snapshot([row()])
    for t in (300, 301):
        clock.value = t
        manager.process_snapshot([row(t, EMI_SITES[:1])])
    clock.value = 330
    central.source.acquire.return_value = (row(330, EMI_SITES[:1]),)
    central.tick()  # Confirmation is queued, not yet processed.
    clock.value = 360
    central.source.acquire.side_effect = OfficialAcquisitionError(ErrorKind.AUTHORIZATION)
    central.tick()
    assert state(manager, watch).status == WatchStatus.FAILED
    fleet.cycle(); fleet.cycle()
    terminal.assert_called_once()
    notify.assert_not_called()


def test_cli_admission_origin_precedes_presentation_callback():
    clock, central, _, _, _ = rig()
    central.tick()
    def resolved(vehicle):
        clock.value = 101  # Presentation must not move the admission origin.
    runner = WatchRunner(SnapshotSource(central), row().plate, None, Mock(),
                         WatchConfig(inactivity_seconds=100), now=clock.wall,
                         on_resolved=resolved)
    assert runner.run() == 1 and runner.failure_code == 'inactivity'
    assert runner.continuity.activity_at == 0
    runner.notifier.send_arrival.assert_not_called()
