import csv
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from threading import Event
from unittest.mock import Mock

import pytest

from gps_emi.analysis.collector import ObservationStore, PassiveCollector, EXPORT_COLUMNS
from gps_emi.analysis.export_observations import main, timestamp
from gps_emi.clock import acquisition_now
from gps_emi.models import Vehicle
from gps_emi.monitoring.fleet_polling import FleetPolling
from gps_emi.monitoring.watches import WatchManager
from gps_emi.providers.widetech import normalize_vehicle, parse

NOW = datetime(2026, 9, 24, 12, tzinfo=timezone(timedelta(hours=-5)))
GPS = datetime(2026, 9, 24, 11, 59)


def vehicle(**changes):
    return replace(Vehicle('synthetic-1', 'TEST001', GPS, mobile_number='TEST-1',
                           latitude=6.2, longitude=-75.5, speed=0, ignition=0, gps_fix=0,
                           zones=['EMI_Medellin_Taller'], zones_raw='<B>EMI_Medellin_Taller</B>'), **changes)


def rows(path):
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute('SELECT * FROM gps_observations ORDER BY id')]


def test_parser_preserves_available_raw_fields_without_changing_zones():
    payload = '''{"Rows":[{"VEHID":"synthetic-1","VEH_NAM":" test001 ",
        "VEH_LCNS":" TEST-1 ","Latitude":"6.2","Longitude":-75.5,
        "Zones":"<B>EMI_Medellin_Taller</B>","Location":"<B>Dirección</B>"}]}'''
    result = normalize_vehicle(parse(payload)[0])
    assert result.latitude == 6.2 and result.longitude == -75.5
    assert result.plate == 'TEST001' and result.mobile_number == 'TEST-1'
    assert result.vehicle_name_raw == ' test001 '
    assert result.vehicle_license_raw == ' TEST-1 '
    assert result.zones_raw == '<B>EMI_Medellin_Taller</B>'
    assert result.zones == ['EMI_Medellin_Taller']
    assert result.location == '<B>Dirección</B>'


def test_schema_optional_fields_and_privacy(tmp_path):
    path = tmp_path / 'new' / 'gps.db'
    store = ObservationStore(path)
    store.initialize()
    assert store.record([Vehicle('', ''), vehicle()], NOW) == 2
    data = rows(path)
    assert data[0]['gps_reported_at'] is None
    assert data[0]['latitude'] is None and data[0]['zones_raw'] is None
    assert json.loads(data[0]['ignition']) is None
    assert data[1]['gps_reported_at'] == GPS.isoformat()
    assert data[1]['acquired_at'] == '2026-09-24T17:00:00.000000+00:00'
    assert data[1]['zones_raw'].startswith('<B>')
    assert json.loads(data[1]['zones']) == ['EMI_Medellin_Taller']
    assert json.loads(data[1]['gps_fix']) == 0
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
    forbidden = {'owner_id', 'notification_target', 'token', 'cookie', 'phone', 'conversation'}
    assert not forbidden.intersection(data[0])
    assert set(data[0]) == set(EXPORT_COLUMNS) | {'fingerprint'}


@pytest.mark.parametrize('changes', [
    {'gps_timestamp': GPS + timedelta(seconds=30)}, {'latitude': 6.21},
    {'longitude': -75.51}, {'speed': 0.01}, {'ignition': 1}, {'gps_fix': 1},
    {'zones': []}, {'zones_raw': '<b>EMI_Medellin_Taller</b>'},
    {'location': 'Nueva dirección'}, {'plate': 'TEST002'},
    {'vehicle_name_raw': 'OTRO'}, {'mobile_number': 'TEST-2'},
])
def test_every_change_is_retained(tmp_path, changes):
    store = ObservationStore(tmp_path / 'gps.db')
    store.record([vehicle()], NOW)
    assert store.record([vehicle(**changes)], NOW + timedelta(seconds=30)) == 1


def test_heartbeat_restart_and_vehicle_identity(tmp_path):
    path = tmp_path / 'gps.db'
    store = ObservationStore(path, 300)
    assert store.record([vehicle()], NOW) == 1
    assert store.record([vehicle()], NOW + timedelta(seconds=299)) == 0
    reopened = ObservationStore(path, 300)
    assert reopened.record([vehicle()], NOW + timedelta(seconds=300)) == 1
    assert reopened.record([vehicle(vehid='synthetic-2')], NOW + timedelta(seconds=301)) == 1
    assert reopened.record([vehicle(vehid='')], NOW) == 1
    assert reopened.record([vehicle(vehid='')], NOW) == 1
    assert len(rows(path)) == 5


def test_aware_clock_and_reject_naive_acquisition(tmp_path):
    assert acquisition_now().utcoffset() == timedelta(hours=-5)
    with pytest.raises(ValueError):
        ObservationStore(tmp_path / 'gps.db').record([vehicle()], GPS)
    assert not (tmp_path / 'gps.db').exists()


def test_transaction_rollback_and_retry(tmp_path):
    path = tmp_path / 'gps.db'
    store = ObservationStore(path)
    with pytest.raises(ValueError):
        store.record([vehicle(), vehicle(speed=float('nan'))], NOW)
    assert rows(path) == []
    assert store.record([vehicle()], NOW) == 1


def test_future_schema_is_not_overwritten(tmp_path):
    path = tmp_path / 'gps.db'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(ValueError):
        ObservationStore(path).initialize()


def test_sqlite_lock_is_recoverable(tmp_path):
    path = tmp_path / 'gps.db'
    store = ObservationStore(path)
    store.initialize()
    locked = sqlite3.connect(path)
    try:
        locked.execute('BEGIN EXCLUSIVE')
        with pytest.raises(sqlite3.OperationalError):
            store.record([vehicle()], NOW)
    finally:
        locked.rollback()
        locked.close()
    assert store.record([vehicle()], NOW) == 1


def test_submit_does_not_wait_for_writer():
    entered, release = Event(), Event()
    store = Mock()
    def blocked_record(*args):
        entered.set()
        assert release.wait(2)
    store.record.side_effect = blocked_record
    collector = PassiveCollector(store)
    collector.start()
    try:
        collector.submit([vehicle()], NOW)
        assert entered.wait(2)
        assert collector.submit([vehicle()], NOW)
        assert not release.is_set()
    finally:
        release.set()
        assert collector.close()


def test_worker_failure_recovery_and_bounded_queue(caplog):
    store = Mock()
    store.initialize.side_effect = sqlite3.OperationalError('synthetic-private-detail')
    completed = Event()
    calls = []
    def record(*args):
        calls.append(args)
        if len(calls) == 1:
            raise sqlite3.OperationalError('synthetic-private-detail')
        completed.set()
    store.record.side_effect = record
    collector = PassiveCollector(store, capacity=2)
    assert collector.submit([vehicle()], NOW)
    assert collector.submit([vehicle()], NOW)
    assert not collector.submit([vehicle()], NOW)
    collector.start()
    assert completed.wait(2)
    assert collector.close()
    assert not collector.submit([vehicle()], NOW)
    assert len(calls) == 2
    assert 'escritura fallida' in caplog.text and 'saturado' in caplog.text
    assert 'synthetic-private-detail' not in caplog.text


def test_worker_creates_and_drains_database(tmp_path):
    path = tmp_path / 'gps.db'
    collector = PassiveCollector(ObservationStore(path))
    original = vehicle()
    collector.submit([original], NOW)
    original.zones.append('Cambio posterior')
    collector.start()
    assert collector.close()
    assert json.loads(rows(path)[0]['zones']) == ['EMI_Medellin_Taller']


@pytest.mark.parametrize('failure', [False, True])
def test_single_snapshot_operational_path_isolated_from_collector(failure):
    source = Mock()
    source.get_vehicles.return_value = [vehicle(zones=[]), vehicle(vehid='synthetic-2')]
    manager = WatchManager(Mock(return_value=True))
    collector = Mock()
    if failure:
        collector.submit.side_effect = sqlite3.OperationalError('private')
    polling = FleetPolling(lambda: source, manager, collector=collector, autostart=False)
    assert polling.cycle() is None  # Captura pasiva: no genera consultas estando inactivo.
    source.get_vehicles.assert_not_called()
    polling.request_watch('owner-synthetic', 'TEST-1', 'target-synthetic', vehicle_id='synthetic-1')
    assert polling.cycle() == 30
    source.get_vehicles.assert_called_once()
    assert len(manager.get_active_watches('owner-synthetic')) == 1
    snapshot, acquired = collector.submit.call_args.args
    assert snapshot == source.get_vehicles.return_value
    assert acquired.tzinfo is not None
    polling.close()


def test_csv_readonly_filters_and_utf8(tmp_path):
    path = tmp_path / 'gps.db'
    store = ObservationStore(path)
    for minute in range(3):
        store.record([vehicle(location=f'Dirección, número {minute}')], NOW + timedelta(minutes=minute))
    before = path.read_bytes()
    output = tmp_path / 'export.csv'
    assert main(['--db', str(path), '--output', str(output), '--from', NOW.isoformat(),
                 '--to', (NOW + timedelta(minutes=2)).isoformat()]) == 0
    with output.open(encoding='utf-8', newline='') as stream:
        result = list(csv.DictReader(stream))
    assert len(result) == 2
    assert result[0]['reported_location'] == 'Dirección, número 0'
    assert tuple(result[0]) == EXPORT_COLUMNS
    assert path.read_bytes() == before
    assert main(['--db', str(path), '--output', str(path)]) == 1
    assert main(['--db', str(path), '--output', str(output)]) == 1
    assert path.read_bytes() == before


def test_export_missing_db_and_invalid_range(tmp_path):
    path = tmp_path / 'missing.db'
    assert main(['--db', str(path), '--output', str(tmp_path / 'out.csv')]) == 1
    assert not path.exists()
    with pytest.raises(SystemExit):
        main(['--db', str(path), '--output', 'unused.csv', '--from', '2026-09-24'])
    assert timestamp('2026-09-24T12:00:00-05:00') == timestamp('2026-09-24T17:00:00Z')


def test_export_empty_and_unbounded(tmp_path):
    path = tmp_path / 'gps.db'
    store = ObservationStore(path)
    store.initialize()
    empty = tmp_path / 'empty.csv'
    assert main(['--db', str(path), '--output', str(empty)]) == 0
    assert empty.read_text(encoding='utf-8').strip() == ','.join(EXPORT_COLUMNS)
    store.record([vehicle()], NOW)
    output = tmp_path / 'all.csv'
    assert main(['--db', str(path), '--output', str(output)]) == 0
    assert main(['--db', str(path), '--output', str(tmp_path / 'invalid.csv'),
                 '--from', NOW.isoformat(), '--to', NOW.isoformat()]) == 1
