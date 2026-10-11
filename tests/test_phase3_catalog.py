"""Phase 3 contracts with synthetic XML, temporary databases and fake clocks."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Barrier
from unittest.mock import Mock
import sqlite3

import pytest

from gps_emi.acquisition import Coordinator, SnapshotSource, SnapshotUnavailable, LabelMapping
from gps_emi.catalog import CatalogStore
from gps_emi.analysis.collector import ObservationStore
from gps_emi.analysis.sessions import SessionStore
from gps_emi.monitoring.fleet_polling import FleetPolling
from gps_emi.monitoring.watches import WatchManager, WatchStatus
from gps_emi.monitoring.runner import WatchRunner
from gps_emi.providers.widetech_official import parse_render_excel, OfficialAcquisitionError, ErrorKind
from gps_emi.queries import get_vehicle_location, get_vehicle_location_by_id, list_vehicles_at_site
from gps_emi.resolution import AmbiguousVehicleError, VehicleNotFoundError
from gps_emi.selection import PendingSelections, SelectionOperation
from gps_emi.sites import EMI_SITES
from test_central_acquisition import Clock, row
from test_widetech_official import payload

MAPPING = LabelMapping('VEH_NAM', 'Movil')


def record(vid='a', **changes):
    return dict({'VEH_ID': vid, 'VEH_NAM': 'TEST-'+vid.upper(), 'Movil': 'MOBILE-'+vid,
                 'fltName': 'Ambulancias Medellín', 'FechaGPS': '2025-12-31 19:00:00',
                 'Zones': ''}, **changes)


def batch(*records):
    return parse_render_excel(payload(list(records)))


def rig(tmp_path, *results):
    store = CatalogStore(tmp_path/'catalog.db')
    store.initialize()
    clock = Clock()
    transport = Mock(acquire=Mock(side_effect=results))
    central = Coordinator(transport, monotonic=clock.mono, utcnow=clock.utc, catalog=store, mapping=MAPPING)
    central.demand('test', True)
    return central, SnapshotSource(central, MAPPING), clock, store


def step(central, clock):
    clock.value = max(clock.value, central.next_start)
    return central.tick()


def sql(store, query):
    with sqlite3.connect(store.path) as db:
        return db.execute(query).fetchall()


def entry(central, vid='a'):
    return next(v for v in central.peek().catalog.entries if v.vehicle_id == vid)


def test_national_queries_and_explicit_medellin_consumers(tmp_path):
    data = batch(record('a'), record('b', fltName=' Ambulancias Bogotá ', Zones=EMI_SITES[0]),
                 record('c', fltName='Otra compañía'))
    central, source, clock, store = rig(tmp_path, data)
    collector = Mock(active=True)
    manager = WatchManager(Mock())
    errors = Mock()
    fleet = FleetPolling(lambda: source, manager, collector=collector, on_error=errors, autostart=False)
    fleet.request_watch('a', 'TEST-A', 'a')
    fleet.request_watch('b', 'TEST-B', 'b')
    assert step(central, clock); fleet.cycle()
    assert {v.vehid for v in source.get_vehicles()} == {'a','b'}
    assert get_vehicle_location(source, 'MOBILE-b').vehicle.vehid == 'b'
    assert get_vehicle_location_by_id(source, 'b').vehicle.plate == 'TEST-B'
    assert [r.vehicle.vehid for r in list_vehicles_at_site(source, EMI_SITES[0]).entries] == ['b']
    assert manager.active_count() == 1 and errors.call_count == 1
    assert [v.vehid for v in collector.submit.call_args.args[0]] == ['a','b']
    assert {e.vehicle_id for e in central.peek().catalog.entries} == {'a','b','c'}
    fleet.close()


def test_renaming_and_duplicate_labels_keep_identity_and_selector(tmp_path):
    central, source, clock, store = rig(tmp_path, batch(record('a'), record('b', fltName='Ambulancias Cali')),
        batch(record('a', VEH_NAM='SAME', Movil='NEW-A'), record('b', VEH_NAM='SAME', fltName='Ambulancias Cali')))
    step(central, clock)
    first_seen = entry(central).first_seen
    manager = WatchManager(Mock())
    fleet = FleetPolling(lambda: source, manager, autostart=False)
    fleet.request_watch('owner','TEST-A','target'); fleet.cycle()
    step(central, clock); fleet.cycle()
    watched, = manager.get_active_watches('owner')
    assert watched.vehicle_id == 'a' and watched.plate == 'SAME'
    assert entry(central).first_seen == first_seen and entry(central).last_seen != first_seen
    with pytest.raises(AmbiguousVehicleError) as caught:
        get_vehicle_location(source, 'SAME')
    pending = PendingSelections()
    gen = pending.begin('owner')
    context = pending.offer('owner', SelectionOperation.LOCATION, 'SAME', caught.value.candidates,
                            'target', gen, reports=caught.value.candidate_reports)
    _, selected = pending.consume('owner',context.selection_id,context.choice_ids[1])
    assert get_vehicle_location_by_id(source,selected).vehicle.vehid == 'b'
    assert sql(store,'SELECT count(*) FROM catalog_events')[0][0] == 0
    fleet.close()


@pytest.mark.parametrize('bad', [dict(fltName='ABSENT'), dict(fltName=None), dict(duplicate=True)])
def test_unknown_fleet_and_duplicate_identity_do_not_terminate(tmp_path, bad):
    rows = [record('a', **{k:v for k,v in bad.items() if k!='duplicate'})]
    if bad.get('duplicate'):
        rows.append(record('a', fltName='Otra'))
    central, source, clock, store = rig(tmp_path, batch(record()), batch(*rows))
    notify = Mock()
    manager = WatchManager(notify)
    fleet = FleetPolling(lambda: source, manager, autostart=False)
    fleet.request_watch('owner','TEST-A','target')
    step(central, clock); fleet.cycle()
    first = entry(central)
    step(central, clock); fleet.cycle()
    assert manager.active_count() == 1
    assert entry(central).fleet_name == first.fleet_name
    assert entry(central).presence == 'present'
    notify.assert_not_called()
    fleet.close()


def test_confirmed_reclassification_with_bad_gps_terminates_silently(tmp_path):
    central, source, clock, store = rig(tmp_path, batch(record()),
        batch(record(fltName='Otra compañía', FechaGPS='bad')))
    notify, terminal = Mock(), Mock()
    manager = WatchManager(notify)
    fleet = FleetPolling(lambda: source, manager, on_terminal=terminal, autostart=False)
    fleet.request_watch('owner','TEST-A','target')
    step(central,clock); fleet.cycle()
    step(central,clock); fleet.cycle()
    watched, = manager.list_watches('owner')
    assert watched.status == WatchStatus.FAILED and watched.failure_code == 'fleet_changed'
    assert entry(central).presence == 'present' and entry(central).fleet_name == 'Otra compañía'
    assert source.get_vehicles() == []
    notify.assert_not_called(); terminal.assert_not_called()
    assert sql(store,'SELECT count(*) FROM catalog_events')[0][0] == 0
    fleet.close()


def test_cli_reclassification_reuses_runner(tmp_path, monkeypatch):
    central, source, clock, store = rig(tmp_path, batch(record()), batch(record(fltName='Ambulancias Cali', FechaGPS='bad')))
    def wait(**kwargs):
        pending = central.request(refresh=True)
        assert step(central,clock)
        return pending.result()
    monkeypatch.setattr(source,'wait',wait)
    notifier = Mock()
    runner = WatchRunner(source,'TEST-A',None,notifier)
    assert runner.run() == 1 and runner.failure_code == 'fleet_changed'
    assert not central.subscribers
    notifier.send_arrival.assert_not_called()


def test_cli_does_not_miss_reclassification_between_consumed_versions(tmp_path, monkeypatch):
    central, source, clock, store = rig(tmp_path, batch(record()),
        batch(record(fltName='Otra')), batch(record()))
    calls = []
    def wait(**kwargs):
        step(central,clock)
        if calls:
            step(central,clock)  # Back in Medellin before the CLI resumes reading.
        calls.append(True)
        return central.peek()
    monkeypatch.setattr(source,'wait',wait)
    runner = WatchRunner(source,'TEST-A',None,Mock())
    assert runner.run() == 1 and runner.failure_code == 'fleet_changed'


def test_cli_rejects_national_vehicle_for_watch(tmp_path, monkeypatch):
    central, source, clock, store = rig(tmp_path, batch(record(fltName='Ambulancias Cali')))
    step(central,clock)
    monkeypatch.setattr(source,'wait',lambda **kwargs:central.peek())
    runner = WatchRunner(source,'TEST-A',None,Mock())
    assert runner.run() == 1 and runner.failure_code == 'not_found'
    assert get_vehicle_location(source,'TEST-A').vehicle.vehid == 'a'


def test_retained_candidates_keep_original_provenance(tmp_path):
    central, source, clock, store = rig(tmp_path,
        batch(record('a',VEH_NAM='SAME'), record('b',VEH_NAM='SAME',fltName='Ambulancias Cali')),
        batch(record('a',VEH_NAM='SAME',FechaGPS='bad'), record('b',VEH_NAM='SAME',fltName='Ambulancias Cali')))
    step(central,clock); step(central,clock)
    with pytest.raises(AmbiguousVehicleError) as caught:
        get_vehicle_location(source,'SAME')
    selections = PendingSelections()
    gen = selections.begin('owner')
    context = selections.offer('owner',SelectionOperation.LOCATION,'SAME',caught.value.candidates,
                               'target',gen,reports=caught.value.candidate_reports)
    retained = context.candidate_reports[0].acquisition
    assert retained.retained and retained.version == 1 and retained.age_seconds == 30
    assert retained.source is not None
    assert selections.view('owner',context.selection_id).candidate_reports[0].acquisition == retained
    from gps_emi.whatsapp.vehicle_selection import selection_payload
    description = selection_payload(context)['action']['sections'][0]['rows'][0]['description']
    assert 'Conservado' in description


def test_three_admitted_acquisitions_and_reappearance(tmp_path):
    central, source, clock, store = rig(tmp_path, batch(record('a'),record('b')),
        *[batch(record('b')) for _ in range(3)], batch(record('a', FechaGPS='bad'),record('b')))
    step(central,clock); first = entry(central).first_seen
    for index in range(3):
        assert step(central,clock)
        assert entry(central).presence == ('disappeared' if index==2 else 'present')
    assert len(sql(store,'SELECT * FROM catalog_events')) == 1
    old = source.get_vehicles()[0]
    for _ in range(10):
        get_vehicle_location_by_id(source,'a'); source.get_vehicles(); store.apply(central.peek())
    assert len(sql(store,'SELECT * FROM catalog_events')) == 1
    assert step(central,clock)
    assert entry(central).presence == 'present' and entry(central).first_seen == first
    assert entry(central).reappeared_at and entry(central).disappeared_at
    assert [r[0] for r in sql(store,'SELECT kind FROM catalog_events ORDER BY id')] == ['disappearance','reappearance']
    assert source.get_vehicles()[0].gps_timestamp == old.gps_timestamp
    assert get_vehicle_location_by_id(source,'a').acquisition.retained


@pytest.mark.parametrize('interruption', [batch(), batch(record('b', fltName='ABSENT')),
    batch(record('b', Velocidad='bad')), batch(record('b'),record('b')),
    OfficialAcquisitionError(ErrorKind.HTTP), OfficialAcquisitionError(ErrorKind.PAYLOAD)])
def test_unfit_or_error_breaks_consecutive_sequence(tmp_path, interruption):
    central, source, clock, store = rig(tmp_path, batch(record('a'),record('b')),
        batch(record('b')), batch(record('b')), interruption,
        batch(record('b')), batch(record('b')), batch(record('b')))
    for _ in range(6):
        step(central,clock)
        assert entry(central).presence == 'present'
    step(central,clock)
    assert entry(central).presence == 'disappeared'


def test_gps_quality_and_presence_are_independent(tmp_path):
    central, source, clock, store = rig(tmp_path, batch(record()),
        batch(record(FechaGPS='bad', Latitude='bad', VEH_NAM='RENAMED')),
        batch(record(FechaGPS='bad', Latitude='bad', VEH_NAM='RENAMED')))
    step(central,clock); acquisition = get_vehicle_location_by_id(source,'a').acquisition
    for _ in range(2):
        step(central,clock)
        assert entry(central).presence == 'present' and entry(central).plate == 'RENAMED'
    report = get_vehicle_location(source,'RENAMED')
    assert report.acquisition.version == acquisition.version
    assert report.acquisition.acquired_at == acquisition.acquired_at
    assert report.acquisition.source == acquisition.source
    assert report.acquisition.age_seconds == 60
    assert not central.peek().catalog.absence_eligible


def test_restart_resets_provisional_counts_but_preserves_events(tmp_path):
    central, source, clock, store = rig(tmp_path, batch(record('a'),record('b')),
        batch(record('b')), batch(record('b')))
    for _ in range(3):step(central,clock)
    central.close()
    restarted, source, clock, store = rig(tmp_path, *[batch(record('b')) for _ in range(3)])
    assert restarted.peek() is None
    with pytest.raises(SnapshotUnavailable):source.get_vehicles()
    for i in range(3):
        step(restarted,clock)
        assert entry(restarted).presence == ('disappeared' if i==2 else 'present')
        assert [v.vehid for v in source.get_vehicles()] == ['b']  # no positions restored
    other = CatalogStore(store.path); other.initialize()
    assert sql(other,'SELECT kind FROM catalog_events') == [('disappearance',)]


def test_persistence_failure_rolls_back_and_does_not_reclassify(tmp_path):
    central, source, clock, store = rig(tmp_path, batch(record()), batch(record(fltName='Otra')),
        batch(record(fltName='Otra')))
    manager = WatchManager(Mock())
    fleet = FleetPolling(lambda: source,manager,autostart=False)
    fleet.request_watch('owner','TEST-A','target')
    step(central,clock); fleet.cycle(); saved = central.peek()
    sql(store,"CREATE TRIGGER fail_catalog BEFORE INSERT ON catalog_acquisitions BEGIN SELECT RAISE(FAIL,'synthetic'); END")
    assert not step(central,clock)
    assert central.peek() is saved and manager.active_count() == 1
    assert sql(store,'SELECT fleet_name FROM catalog_vehicles') == [('Ambulancias Medellín',)]
    assert central.health()['error'] == ('persistence', None)
    sql(store,'DROP TRIGGER fail_catalog')
    assert step(central,clock)
    assert manager.active_count() == 0
    fleet.close()


def test_additive_schema_compatible_with_campaigns_and_concurrent_writes(tmp_path, monkeypatch):
    path = tmp_path/'catalog.db'
    now = datetime(2026,1,1,tzinfo=timezone.utc)
    monkeypatch.setattr('gps_emi.analysis.sessions.acquisition_now',lambda: now)
    legacy = ObservationStore(path); assert legacy.record([row()],now) == 1
    sessions = SessionStore(path); session = sessions.start_session(3600,now)
    central, source, clock, catalog = rig(tmp_path,batch(record()))
    barrier = Barrier(2)
    def publish():
        barrier.wait(); return step(central,clock)
    def collect():
        barrier.wait(); return sessions.record([row()],now)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a,b = pool.submit(publish),pool.submit(collect)
        assert a.result() and b.result() == 0
    assert sql(catalog,'PRAGMA user_version') == [(3,)]
    assert sql(catalog,'PRAGMA journal_mode') == [('wal',)]
    assert sql(catalog,'SELECT collection_session_id FROM gps_observations ORDER BY id') == [(None,)]
    assert sql(catalog,'SELECT session_id FROM collection_observations') == [(session,)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _:catalog.apply(central.peek()),range(8)))
    assert sql(catalog,'SELECT count(*) FROM catalog_acquisitions') == [(1,)]
    assert len(sql(catalog,'SELECT * FROM gps_observations')) == 1


def test_unknown_database_schema_is_not_migrated(tmp_path):
    catalog = CatalogStore(tmp_path/'future.db')
    with sqlite3.connect(catalog.path) as db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(ValueError):catalog.initialize()
    assert sql(catalog,"SELECT name FROM sqlite_master WHERE name LIKE 'catalog_%'") == []


def test_locked_database_preserves_snapshot_and_resets_misses(tmp_path):
    central, source, clock, store = rig(tmp_path,batch(record('a'),record('b')),
        *[batch(record('b')) for _ in range(6)])
    for _ in range(3):step(central,clock)
    saved = central.peek()
    blocker = sqlite3.connect(store.path)
    blocker.execute('BEGIN IMMEDIATE')
    try:
        assert not step(central,clock)
        assert central.peek() is saved and central.health()['error'] == ('persistence',None)
    finally:
        blocker.rollback(); blocker.close()
    for i in range(3):
        assert step(central,clock)
        assert entry(central).presence == ('disappeared' if i==2 else 'present')


def test_queued_old_fleet_cannot_admit_a_new_watch(tmp_path):
    central, source, clock, store = rig(tmp_path, batch(record()),
        batch(record(fltName='Otra compañía')))
    notify, errors = Mock(), Mock()
    manager = WatchManager(notify)
    fleet = FleetPolling(lambda: source, manager, on_error=errors, autostart=False)
    fleet.request_watch('owner', 'TEST-A', 'target')
    step(central, clock); step(central, clock)
    fleet.cycle()
    assert not manager.list_watches('owner')
    fleet.cycle()
    assert not manager.list_watches('owner')
    assert errors.call_count == 1
    notify.assert_not_called()
    fleet.close()


def test_backlog_does_not_revert_current_name_or_modify_original_gps(tmp_path):
    central, source, clock, store = rig(tmp_path, batch(record()),
        batch(record(FechaGPS='2025-12-31 19:00:30')),
        batch(record(VEH_NAM='RENAMED', FechaGPS='bad')))
    manager = WatchManager(Mock())
    fleet = FleetPolling(lambda: source, manager, autostart=False)
    fleet.request_watch('owner', 'TEST-A', 'target')
    step(central, clock); fleet.cycle()
    step(central, clock); step(central, clock)
    assert manager.get_active_watches('owner')[0].plate == 'RENAMED'
    fleet.cycle()
    assert manager.get_active_watches('owner')[0].plate == 'RENAMED'
    assert central.peek().operational[0].record.raw['VEH_NAM'] == 'TEST-A'
    fleet.cycle()
    assert manager.get_active_watches('owner')[0].plate == 'RENAMED'
    fleet.close()
