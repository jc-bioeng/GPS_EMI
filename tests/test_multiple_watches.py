from snapshot_fakes import ScriptedSnapshots, publish
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from threading import Barrier, Event, Thread
from unittest.mock import Mock

import pytest

from gps_emi.config import WatchConfig
from gps_emi.errors import SessionExpiredError, TransientAcquisitionError
from gps_emi.models import Vehicle
from gps_emi.monitoring.arrival import MonitorState
from gps_emi.monitoring.observation import ObservationStatus
from gps_emi.monitoring.watches import WatchManager, WatchStatus
from gps_emi.monitoring.fleet_polling import FleetPolling
from gps_emi.sites import EMI_SITES

BASE = datetime(2026, 9, 22, 12)


def vehicle(vid='1', seconds=0, sites=(), **kwargs):
    return Vehicle(vid, 'PLATE' + vid, BASE + timedelta(seconds=seconds),
                   mobile_number='AMB-' + vid, zones=list(sites), **kwargs)


def setup_fleet(rows, config=None):
    notify, source = Mock(return_value=True), Mock()
    source.get_vehicles.side_effect = rows
    manager = WatchManager(notify, config, now=lambda: BASE + timedelta(minutes=10))
    created, errors = Mock(), Mock()
    polling = FleetPolling(lambda: ScriptedSnapshots(source), manager, config=config, autostart=False,
                           on_created=created, on_error=errors)
    return manager, polling, source, notify, created, errors


def test_four_snapshots_three_independent_watches():
    a, b, c = vehicle('20'), vehicle('18'), replace(vehicle('96'), mobile_number='MOVIL- 96')
    snapshots = [[a, b, replace(c, zones=[EMI_SITES[1]])],
        [replace(a, gps_timestamp=BASE+timedelta(seconds=30), zones=[EMI_SITES[0]]), replace(b, gps_timestamp=BASE+timedelta(seconds=30)), replace(c, gps_timestamp=BASE+timedelta(seconds=30), zones=[EMI_SITES[1]])],
        [replace(b, gps_timestamp=BASE+timedelta(seconds=60), zones=[EMI_SITES[1]]), replace(c, gps_timestamp=BASE+timedelta(seconds=60))],
        [replace(c, gps_timestamp=BASE+timedelta(seconds=90), zones=[EMI_SITES[0]])]]
    manager, polling, source, notify, created, errors = setup_fleet(snapshots)
    for v in (a,b,c):
        polling.request_watch('A', v.mobile_number, 'destination-A')
    for index, expected in enumerate((0,1,2,3)):
        publish(polling)
        assert notify.call_count == expected
        assert len(manager.get_active_watches('A')) == 3-expected
        assert source.get_vehicles.call_count == index+1
    assert not polling.active
    assert publish(polling) is None
    assert source.get_vehicles.call_count == 4
    assert {call.args[0].notification_target for call in notify.call_args_list} == {'destination-A'}
    assert [call.args[1].vehicle.vehid for call in notify.call_args_list] == ['20','18','96']
    assert all(w.status == WatchStatus.COMPLETED and w.notification_status == 'accepted' for w in manager.list_watches('A'))
    errors.assert_not_called()


def test_owner_isolation_duplicates_and_independent_monitors():
    manager = WatchManager(Mock(), now=lambda: BASE)
    a, fresh = manager.create_watch('A', vehicle(), 'target-A')
    again, fresh_again = manager.create_watch('A', replace(vehicle(), plate='changed'), 'other-target')
    b, _ = manager.create_watch('B', vehicle(), 'target-B')
    assert fresh and not fresh_again and again.watch_id == a.watch_id
    assert again.notification_target == 'target-A'
    assert a.watch_id != b.watch_id and a.monitor is not b.monitor
    assert manager.get_watch('A', b.watch_id) is None
    assert manager.cancel_watch('A', b.watch_id) is None
    assert [w.watch_id for w in manager.list_watches('A')] == [a.watch_id]
    assert manager.cancel_watch('A', a.watch_id).status == WatchStatus.CANCELLED
    assert len(manager.get_active_watches('B')) == 1
    assert manager.get_watch('A', a.watch_id).status == WatchStatus.CANCELLED
    new, fresh = manager.create_watch('A', vehicle(), 'target-A')
    assert fresh and new.watch_id != a.watch_id
    # Las vistas no permiten alterar el estado almacenado.
    new.status = WatchStatus.CANCELLED
    assert manager.get_watch('A', new.watch_id).status == WatchStatus.ACTIVE


@pytest.mark.parametrize('identifier', ['AMB-1','amb1','PLATE1'])
def test_resolve_once_then_follow_vehid(identifier):
    manager, polling, source, notify, _, _ = setup_fleet([[vehicle()], [replace(vehicle(seconds=30, sites=EMI_SITES), plate='NEW', mobile_number='NEW')]])
    polling.request_watch('A', identifier, 'target')
    publish(polling); publish(polling)
    event = notify.call_args.args[1]
    assert event.vehicle.vehid == '1' and event.vehicle.plate == 'NEW'
    assert event.sites == EMI_SITES and event.site is None
    assert manager.list_watches('A')[0].status == WatchStatus.COMPLETED


@pytest.mark.parametrize('first,second', [(EMI_SITES[:1], EMI_SITES[1:]), (EMI_SITES[1:], EMI_SITES[:1]), (EMI_SITES, EMI_SITES[:1])])
def test_first_inside_and_site_change_need_outside(first, second):
    manager, polling, _, notify, _, _ = setup_fleet([
        [vehicle(sites=first)], [vehicle(seconds=1,sites=second)],
        [vehicle(seconds=2)], [vehicle(seconds=3,sites=first)]])
    polling.request_watch('A','AMB-1','target')
    publish(polling); publish(polling)
    notify.assert_not_called()
    publish(polling); publish(polling)
    notify.assert_called_once()


@pytest.mark.parametrize('bad,status', [
    (vehicle(sites=EMI_SITES), ObservationStatus.DUPLICATE),
    (vehicle(seconds=-1,sites=EMI_SITES), ObservationStatus.OUT_OF_ORDER),
    (replace(vehicle(sites=EMI_SITES),gps_timestamp=None), ObservationStatus.MISSING_TIMESTAMP),
])
def test_bad_timestamp_only_affects_its_watch(bad,status):
    manager, polling, _, notify, _, _ = setup_fleet([[vehicle(),vehicle('2')], [bad,vehicle('2',30,EMI_SITES)]])
    polling.request_watch('A','AMB-1','target'); polling.request_watch('A','AMB-2','target')
    publish(polling); publish(polling)
    first, second = manager.list_watches('A')
    assert first.status == WatchStatus.ACTIVE and first.last_assessment.status == status
    assert second.status == WatchStatus.COMPLETED
    assert notify.call_count == 1


@pytest.mark.parametrize('missing', [[], [vehicle(),vehicle()]])
def test_absent_or_ambiguous_vehicle_keeps_watch(missing):
    manager, polling, _, notify, _, _ = setup_fleet([[vehicle()], missing, [vehicle(seconds=30,sites=EMI_SITES)]])
    polling.request_watch('A','AMB-1','target')
    publish(polling); publish(polling)
    assert manager.list_watches('A')[0].status == WatchStatus.ACTIVE
    publish(polling)
    notify.assert_called_once()


def test_stale_and_gps_fix_zero_still_process():
    manager, polling, _, notify, _, _ = setup_fleet([[vehicle(gps_fix=0)], [vehicle(seconds=1,sites=EMI_SITES,gps_fix=0)]])
    polling.request_watch('A','AMB-1','target')
    publish(polling); publish(polling)
    watch = manager.list_watches('A')[0]
    assert watch.last_assessment.is_stale(300)
    assert watch.last_observation.gps_fix == 0
    notify.assert_called_once()


def test_global_backoff_recovery_and_terminal_error(caplog):
    manager, polling, source, notify, _, errors = setup_fleet([
        [vehicle(), vehicle('2')], TransientAcquisitionError(), TransientAcquisitionError(),
        [vehicle(seconds=30), vehicle('2',30)], SessionExpiredError()])
    polling.request_watch('A', 'AMB-1', 'target')
    polling.request_watch('A', 'AMB-2', 'target')
    publish(polling)
    publish(polling)
    assert polling.coordinator.backoff == 30
    publish(polling)
    assert polling.coordinator.backoff == 60
    assert len(manager.get_active_watches('A')) == 2
    publish(polling)
    assert polling.coordinator.backoff == 30
    assert 'recuperada' in caplog.text
    publish(polling)
    assert polling.coordinator.blocked
    assert all(w.status == WatchStatus.FAILED for w in manager.list_watches('A'))
    assert not manager.has_active()
    notify.assert_not_called()

def test_pending_creation_survives_transient_failure():
    manager, polling, _, _, created, _ = setup_fleet([TransientAcquisitionError(), [vehicle()]])
    polling.request_watch('A','AMB-1','target')
    publish(polling)
    created.assert_not_called()
    publish(polling)
    created.assert_called_once()


def test_concurrent_duplicate_creation():
    manager = WatchManager(Mock())
    barrier = Barrier(8)
    def create(_):
        barrier.wait(timeout=2)
        return manager.create_watch('A',vehicle(),'target')
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(create, range(8)))
    assert sum(created for _,created in results) == 1
    assert len({w.watch_id for w,_ in results}) == 1


def test_concurrent_arrival_and_notification_failure_no_duplicates():
    entered, release = Event(), Event()
    def notify(watch,event):
        entered.set()
        assert release.wait(timeout=2)
        raise RuntimeError('private transport data')
    manager = WatchManager(notify, now=lambda: BASE)
    watch,_ = manager.create_watch('A',vehicle(),'target')
    manager.process_snapshot([vehicle()])
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(manager.process_snapshot,[vehicle(seconds=1,sites=EMI_SITES)])
        try:
            assert entered.wait(timeout=1)
            # Lectura/cancelación no esperan el HTTP; COMPLETED ya está reservado.
            assert manager.get_watch('A',watch.watch_id).status == WatchStatus.COMPLETED
            assert manager.cancel_watch('A',watch.watch_id) is None
            assert pool.submit(manager.process_snapshot,[vehicle(seconds=2,sites=EMI_SITES)]).result(timeout=1) == []
        finally:
            release.set()
        first.result(timeout=1)
    assert manager.get_watch('A',watch.watch_id).notification_status == 'failed'
    assert manager.process_snapshot([vehicle(seconds=3,sites=EMI_SITES)]) == []


def test_cancellation_and_creation_during_acquisition():
    manager, polling, source, notify, created, _ = setup_fleet([])
    watch,_ = manager.create_watch('A',vehicle(),'target')
    entered,release = Event(),Event()
    def acquire():
        entered.set()
        assert release.wait(timeout=2)
        return [vehicle(seconds=30,sites=EMI_SITES),vehicle('2')]
    source.get_vehicles.side_effect = acquire
    thread = Thread(target=lambda: publish(polling))
    thread.start()
    try:
        assert entered.wait(timeout=1)
        assert manager.cancel_watch('A',watch.watch_id)
        polling.request_watch('A','AMB-2','target')
    finally:
        release.set(); thread.join(timeout=1)
    assert not thread.is_alive()
    notify.assert_not_called()
    created.assert_called_once()  # La alta comparte la adquisición en curso.
    polling.cycle()
    assert len(manager.get_active_watches('A')) == 1


def test_delivery_failure_does_not_prevent_other_watch_notification():
    calls = []
    def notify(watch,event):
        calls.append(watch.notification_target)
        if watch.owner_id == 'A':
            raise RuntimeError()
        return True
    manager = WatchManager(notify, now=lambda: BASE)
    manager.create_watch('A',vehicle(),'target-A')
    manager.create_watch('B',vehicle(),'target-B')
    manager.process_snapshot([vehicle()])
    manager.process_snapshot([vehicle(seconds=1,sites=EMI_SITES)])
    assert calls == ['target-A','target-B']
    assert manager.list_watches('A')[0].notification_status == 'failed'
    assert manager.list_watches('B')[0].notification_status == 'accepted'


def test_shutdown_during_acquisition_discards_snapshot():
    manager, polling, source, notify, _, _ = setup_fleet([])
    entered, release = Event(), Event()
    def acquire():
        entered.set()
        assert release.wait(timeout=3)
        return [vehicle()]
    source.get_vehicles.side_effect = acquire
    polling.request_watch('A', 'AMB-1', 'target')
    central = polling.coordinator
    central.start()
    try:
        assert entered.wait(timeout=3)
        assert not central.close(timeout=0)
        assert polling.close(timeout=0)
    finally:
        release.set()
        assert central.close(timeout=3)
    assert central.peek() is None
    assert not manager.list_watches('A')
    assert not polling.request_watch('A', 'AMB-1', 'target')
    notify.assert_not_called()

def test_local_observation_failure_isolated():
    manager = WatchManager(Mock(return_value=True), now=lambda: BASE)
    manager.create_watch('A',vehicle(),'target')
    manager.create_watch('A',vehicle('2'),'target')
    manager.process_snapshot([vehicle(),vehicle('2')])
    manager.process_snapshot([replace(vehicle(),gps_timestamp='invalid'),vehicle('2',1,EMI_SITES)])
    first,second = manager.list_watches('A')
    assert first.status == WatchStatus.FAILED and second.status == WatchStatus.COMPLETED


@pytest.mark.parametrize('recoverable', [False,True])
def test_polling_shutdown_interrupts_interval_and_backoff(recoverable):
    manager, polling, source, _, _, _ = setup_fleet([])
    entered = Event()
    def acquire():
        entered.set()
        if recoverable:
            raise TransientAcquisitionError()
        return [vehicle()]
    source.get_vehicles.side_effect = acquire
    polling.autostart = True
    polling.request_watch('A', 'AMB-1', 'target')
    polling.coordinator.start()
    try:
        assert entered.wait(timeout=3)
    finally:
        polling.coordinator.request_stop()
        assert polling.close(timeout=1)
        assert polling.coordinator.close(timeout=1)
    assert source.get_vehicles.call_count == 1
    assert not polling.active

def test_recovery_preserves_both_outside_states_until_arrival():
    manager, polling, source, notify, _, _ = setup_fleet([
        [vehicle(),vehicle('2')], TransientAcquisitionError(),
        [vehicle(seconds=1,sites=EMI_SITES[:1]),vehicle('2',1,EMI_SITES[1:])]])
    polling.request_watch('A','AMB-1','target'); polling.request_watch('A','AMB-2','target')
    publish(polling);publish(polling);publish(polling)
    assert notify.call_count == 2
    assert source.get_vehicles.call_count == 3
    assert not manager.has_active()


def test_terminal_error_announces_only_active_watches_and_pending():
    manager, polling, source, notify, _, errors = setup_fleet([SessionExpiredError()])
    active,_ = manager.create_watch('A',vehicle(),'target')
    cancelled,_ = manager.create_watch('A',vehicle('2'),'target')
    manager.cancel_watch('A',cancelled.watch_id)
    polling.request_watch('B','AMB-3','target-B')
    terminal = Mock()
    polling.on_terminal = terminal
    publish(polling)
    terminal.assert_called_once()
    assert terminal.call_args.args[0].watch_id == active.watch_id
    assert errors.call_args.args[0].owner_id == 'B'
    assert manager.get_watch('A',cancelled.watch_id).status == WatchStatus.CANCELLED
    assert not polling.active


def test_cancel_before_arrival_prevents_only_that_event():
    manager = WatchManager(Mock(return_value=True),now=lambda:BASE)
    first,_ = manager.create_watch('A',vehicle(),'target')
    manager.create_watch('A',vehicle('2'),'target')
    manager.process_snapshot([vehicle(),vehicle('2')])
    assert manager.cancel_watch('A',first.watch_id)
    manager.process_snapshot([vehicle(seconds=1,sites=EMI_SITES),vehicle('2',1,EMI_SITES)])
    manager.notify.assert_called_once()
    assert manager.notify.call_args.args[1].vehicle.vehid == '2'


def test_safe_logs_do_not_include_owner_or_notification_target(caplog):
    manager = WatchManager(Mock(return_value=True),now=lambda:BASE)
    owner, target = '15555550123','15555550987'
    manager.create_watch(owner,vehicle(),target)
    manager.process_snapshot([vehicle()])
    manager.process_snapshot([vehicle(seconds=1,sites=EMI_SITES)])
    assert owner not in caplog.text and target not in caplog.text
