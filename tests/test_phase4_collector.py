"""Phase 4: synthetic observations, temporary SQLite, controlled clocks only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event
from unittest.mock import Mock
import csv
import sqlite3

import pytest

from gps_emi.analysis.collector import ObservationStore, EXPORT_COLUMNS, METADATA_COLUMNS
from gps_emi.analysis.sessions import SessionStore, SessionCollector
from gps_emi.analysis.export_observations import export_csv
from gps_emi.database import utc_text
from gps_emi.monitoring.fleet_polling import FleetPolling
from gps_emi.monitoring.watches import WatchManager
from test_phase3_catalog import rig, batch, record, step
from test_collector import vehicle, NOW


@pytest.fixture
def clock(monkeypatch):
    clock = [NOW]
    monkeypatch.setattr('gps_emi.analysis.sessions.acquisition_now', lambda: clock[0])
    return clock


def query(store, sql, args=()):
    with sqlite3.connect(store.path) as db:
        return db.execute(sql, args).fetchall()


def test_global_keys_collisions_names_ids_and_out_of_order(tmp_path):
    store = ObservationStore(tmp_path/'data.db')
    v = vehicle(provenance='synthetic-provider', provider_record_id='same', fleet_name='Ambulancias A')
    assert store.record([v], NOW) == 1
    assert store.record([replace(v, plate='RENAMED', fleet_name='Ambulancias B',
                                  server_original='later', provider_record_id='changed')], NOW) == 0
    assert store.record([replace(v, latitude=1)], NOW) == 1  # timestamp collision
    assert store.record([replace(v, gps_timestamp=v.gps_timestamp-timedelta(seconds=30))], NOW) == 1
    assert store.record([replace(v, vehid='different')], NOW) == 1  # same provider Id
    assert ObservationStore(store.path).record([v], NOW+timedelta(days=1)) == 0
    assert query(store,'SELECT plate,fleet_name,provider_record_id,historical,timestamp_collision FROM gps_observations WHERE vehicle_id=? ORDER BY id',(v.vehid,)) == [
        ('TEST001','Ambulancias A','same',0,0), ('TEST001','Ambulancias A','same',0,1),
        ('TEST001','Ambulancias A','same',1,0)]


def test_same_observation_is_associated_with_later_campaign_without_rewriting(tmp_path,clock):
    store = SessionStore(tmp_path/'data.db')
    one=store.start_session(60)
    assert store.record([vehicle()],clock[0]) == 1
    original=query(store,'SELECT * FROM gps_observations')
    store.status(stop=True)
    clock[0]+=timedelta(seconds=10)
    two=store.start_session(60)
    assert store.record([vehicle(plate='RENAMED')],clock[0]) == 0
    assert query(store,'SELECT * FROM gps_observations') == original
    assert store.status()['observations'] == 1
    assert {r[0] for r in query(store,'SELECT session_id FROM collection_observations')} == {one,two}
    out=tmp_path/'campaign.csv'
    assert export_csv(store.path,out,start=utc_text(clock[0]),session_id=two) == 1
    with out.open(encoding='utf-8',newline='') as f:
        rows=list(csv.DictReader(f))
    assert tuple(rows[0])[:len(EXPORT_COLUMNS)+1] == EXPORT_COLUMNS+('collection_session_id',)
    assert rows[0]['collection_session_id'] == two
    assert rows[0]['acquired_at'] == utc_text(NOW)
    assert rows[0]['session_received_at'] == utc_text(clock[0])


def test_national_mixed_batch_originals_and_operational_order(tmp_path):
    central,source,clk,catalog=rig(tmp_path,
        batch(record('a',fltName='Ambulancias Cali', FechaGPS='2026-01-01 00:01:00', Id='id-original'),record('b',fltName='ABSENT')),
        batch(record('a',fltName='Ambulancias Cali',FechaGPS='2026-01-01 00:00:00',VEH_NAM='RENAMED',Id='older')))
    store=ObservationStore(tmp_path/'history.db')
    step(central,clk)
    first=central.peek()
    assert not first.catalog.absence_eligible
    assert source.get_vehicles(purpose='watch') == []
    assert store.record(source.get_vehicles(purpose='collector'),first.acquired_at) == 1
    step(central,clk)
    assert source.get_vehicles()[0].gps_timestamp == first.operational[0].record.gps_timestamp.replace(tzinfo=None)
    assert central.peek().operational[0].retained_reason == 'out_of_order'
    captured=source.get_vehicles(purpose='collector')
    assert len(captured)==1 and captured[0].plate=='RENAMED'
    assert store.record(captured,central.peek().acquired_at)==1
    assert query(store,'SELECT provider_record_id,gps_original,historical FROM gps_observations ORDER BY id') == [
        ('id-original','2026-01-01 00:01:00',0),('older','2026-01-01 00:00:00',1)]
    assert source.get_vehicles(include_retained=False,purpose='watch')==[]


@pytest.mark.parametrize('close', ['stop','expire'])
def test_begun_write_finishes_after_close_and_queued_work_does_not(tmp_path,clock,close):
    store=SessionStore(tmp_path/'data.db'); sid=store.start_session(60)
    token='synthetic-admission'
    assert store.admit(clock[0],clock[0],token)==sid
    if close=='stop':store.status(stop=True)
    else:
        clock[0]+=timedelta(seconds=60);store.status()
    assert store.record([vehicle()],NOW,token=token)==1
    assert store.record([vehicle()],NOW,token=token)==0
    assert store.record([vehicle(speed=1)],NOW)==0
    assert query(store,'SELECT state FROM collection_batches')==[('written',)]


def test_failed_write_retry_keeps_admission_and_rolls_back_all_rows(tmp_path,clock):
    store=SessionStore(tmp_path/'data.db');store.start_session(60)
    with pytest.raises(ValueError):
        store.record([vehicle(),vehicle(speed=float('nan'))],NOW,token='retry')
    assert query(store,'SELECT * FROM gps_observations')==[]
    assert query(store,'SELECT * FROM observation_keys')==[]
    store.status(stop=True)
    assert store.record([vehicle()],NOW,token='retry')==1
    assert SessionStore(store.path).record([vehicle()],NOW,token='retry')==0


def test_cache_and_inflight_before_start_are_excluded(tmp_path,clock):
    store=SessionStore(tmp_path/'data.db')
    start=clock[0]
    store.start_session(60)
    clock[0]+=timedelta(seconds=5)
    assert store.record([vehicle()],start-timedelta(seconds=1))==0
    assert store.record([vehicle()],clock[0],started_at=start-timedelta(seconds=1))==0
    assert store.record([vehicle()],clock[0],started_at=start+timedelta(seconds=1))==1


def test_stop_and_admission_are_serialized(tmp_path,clock):
    store=SessionStore(tmp_path/'data.db');store.start_session(60)
    entered,release=Event(),Event()
    original=store._write
    def blocked(*args):
        entered.set();assert release.wait(3)
        return original(*args)
    store._write=blocked
    with ThreadPoolExecutor(max_workers=2) as pool:
        writing=pool.submit(store.record,[vehicle()],NOW)
        assert entered.wait(3)
        stopping=pool.submit(SessionStore(store.path).status,stop=True)
        release.set()
        assert writing.result()==1
        assert stopping.result()['status']=='STOPPED'
    assert store.status()['observations']==1


def test_restarts_record_uncertain_interruption_without_extending_end(tmp_path,clock):
    store=SessionStore(tmp_path/'data.db');store.start_session(60)
    first=SessionCollector(store);first.refresh()
    end=store.status()['planned_end_at']
    clock[0]+=timedelta(seconds=10);first.refresh()
    clock[0]+=timedelta(seconds=10)
    resumed=SessionCollector(SessionStore(store.path));resumed.refresh()
    assert resumed.active and store.status()['planned_end_at']==end
    resumed.refresh()
    assert query(store,'SELECT last_observed_at,detected_at,reason FROM collection_interruptions')==[
        (utc_text(NOW+timedelta(seconds=10)),utc_text(clock[0]),'restart_window')]
    clock[0]+=timedelta(seconds=60)
    expired=SessionCollector(SessionStore(store.path));expired.refresh()
    assert not expired.active
    assert store.status()['stopped_at']==end
    assert len(query(store,'SELECT * FROM collection_interruptions'))==2
    assert query(store,'SELECT * FROM gps_observations')==[]


def test_sqlite_lock_then_retry_does_not_duplicate(tmp_path,clock):
    store=SessionStore(tmp_path/'data.db');store.start_session(60)
    with sqlite3.connect(store.path) as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.OperationalError):store.record([vehicle()],NOW,token='lock')
        db.rollback()
    assert store.record([vehicle()],NOW,token='lock')==1
    assert store.record([vehicle()],NOW,token='lock')==0


def legacy_database(path):
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE gps_observations (id INTEGER PRIMARY KEY, acquired_at TEXT NOT NULL,
            vehicle_id TEXT, mobile_number TEXT, plate TEXT, vehicle_name_raw TEXT, vehicle_license_raw TEXT,
            gps_reported_at TEXT, latitude, longitude, speed, ignition TEXT, gps_fix TEXT, zones TEXT,
            zones_raw TEXT, reported_location TEXT, fingerprint TEXT NOT NULL,collection_session_id TEXT)""")
        db.execute("""CREATE TABLE collection_sessions (id TEXT PRIMARY KEY,started_at TEXT NOT NULL,
            planned_end_at TEXT NOT NULL, stopped_at TEXT,status TEXT NOT NULL,
            requested_duration_seconds INTEGER NOT NULL,created_at TEXT NOT NULL,stop_reason TEXT)""")
        db.execute("INSERT INTO collection_sessions VALUES ('old',?,?,?,'COMPLETED',60,?,'duration_elapsed')",
                   (utc_text(NOW),utc_text(NOW),utc_text(NOW),utc_text(NOW)))
        db.execute("INSERT INTO gps_observations VALUES (1,?,'old','MOBILE','TEST',NULL,NULL,?,1,2,0,'0','0','[]',NULL,NULL,'old-key','old')",(utc_text(NOW),NOW.replace(tzinfo=None).isoformat()))
        db.execute('PRAGMA user_version=2')


def test_migration_preserves_legacy_and_catalog_and_is_atomic(tmp_path):
    path=tmp_path/'old.db';legacy_database(path)
    store=SessionStore(path)
    original=query(store,'SELECT * FROM gps_observations')
    class BrokenMigration(SessionStore):
        def _migrate_extra(self,db):
            super()._migrate_extra(db)
            raise ValueError('synthetic migration failure')
    with pytest.raises(ValueError):BrokenMigration(path).initialize()
    assert query(store,'PRAGMA user_version')==[(2,)]
    assert query(store,'SELECT * FROM gps_observations')==original
    store.initialize();store.initialize()
    assert query(store,'SELECT * FROM gps_observations')[0][:len(original[0])]==original[0]
    assert query(store,'SELECT fleet_name,provenance,gps_original FROM gps_observations')==[(None,None,None)]
    assert query(store,'SELECT session_id,observation_id FROM collection_observations')==[('old',1)]
    assert query(store,'PRAGMA user_version')==[(3,)]
    assert export_csv(path,tmp_path/'old.csv',session_id='old')==1


def test_worker_retries_admitted_batch_and_drains_after_close(tmp_path,clock):
    store=SessionStore(tmp_path/'data.db');store.start_session(60)
    collector=SessionCollector(store);collector.refresh()
    original=store._write;calls=[]
    def transient(*args):
        calls.append(True)
        if len(calls)==1:raise sqlite3.OperationalError('synthetic')
        return original(*args)
    store._write=transient
    assert collector.submit([vehicle()],NOW)
    collector.start()
    assert collector.close(timeout=3)
    assert len(calls)==2 and store.status()['observations']==1
    assert not collector.submit([vehicle()],NOW)


def test_expiry_during_data_transaction_does_not_revoke_admission(tmp_path,clock):
    store=SessionStore(tmp_path/'data.db');store.start_session(1)
    original=store._write
    def expire_inside(*args):
        clock[0]+=timedelta(seconds=2)
        return original(*args)
    store._write=expire_inside
    assert store.record([vehicle()],NOW)==1
    assert store.status()['status']=='COMPLETED'
    assert store.status()['observations']==1


def test_old_duplicates_are_preserved_but_not_added_again(tmp_path,clock):
    path=tmp_path/'old.db';legacy_database(path)
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO gps_observations SELECT 2,acquired_at,vehicle_id,mobile_number,plate,vehicle_name_raw,vehicle_license_raw,gps_reported_at,latitude,longitude,speed,ignition,gps_fix,zones,zones_raw,reported_location,fingerprint,collection_session_id FROM gps_observations')
    store=SessionStore(path);store.initialize()
    old=vehicle(vehid='old',plate='RENAMED',gps_timestamp=NOW.replace(tzinfo=None),
                latitude=1,longitude=2,zones=[],zones_raw=None)
    store.start_session(60)
    assert store.record([old],NOW)==0
    assert len(query(store,'SELECT * FROM gps_observations'))==2
    assert store.status()['observations']==1
    assert len(query(store,"SELECT * FROM collection_observations WHERE session_id='old'"))==2


def test_readonly_v2_export_before_migration(tmp_path):
    path=tmp_path/'old.db';legacy_database(path)
    before=path.read_bytes()
    out=tmp_path/'old.csv'
    assert export_csv(path,out,session_id='old')==1
    with out.open(encoding='utf-8',newline='') as f:
        assert tuple(next(csv.reader(f)))==EXPORT_COLUMNS+('collection_session_id',)
    assert path.read_bytes()==before


def test_collector_never_uses_catalog_labels_or_retained_rows(tmp_path):
    central,source,clk,catalog=rig(tmp_path,batch(record()),
        batch(record(VEH_NAM='NEW-NAME',FechaGPS='invalid')))
    step(central,clk);first=source.get_vehicles(purpose='collector')[0]
    step(central,clk)
    assert source.get_vehicles()[0].plate=='NEW-NAME'
    assert source.get_vehicles(purpose='collector')==[]
    assert first.vehicle_name_raw=='TEST-A'
    assert first.gps_original=='2025-12-31 19:00:00'


def test_finished_campaign_does_not_get_false_restart_gap(tmp_path,clock):
    store=SessionStore(tmp_path/'data.db');store.start_session(1)
    collector=SessionCollector(store);collector.refresh()
    clock[0]+=timedelta(seconds=2);collector.refresh()
    clock[0]+=timedelta(seconds=5)
    SessionCollector(store).refresh()
    assert query(store,'SELECT * FROM collection_interruptions')==[]
