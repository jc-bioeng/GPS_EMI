from snapshot_fakes import ScriptedSnapshots, publish
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import csv
import logging
import sqlite3
from unittest.mock import Mock
import pytest

from gps_emi.analysis.collector import ObservationStore
from gps_emi.analysis.sessions import SessionStore, SessionCollector, duration_seconds
from gps_emi.analysis.export_observations import export_csv
from gps_emi.collector import main
from gps_emi.models import Vehicle
from gps_emi.monitoring.fleet_polling import FleetPolling
from gps_emi.monitoring.watches import WatchManager
from gps_emi.errors import SessionExpiredError

NOW = datetime(2026, 10, 2, 17, tzinfo=timezone.utc)


@pytest.fixture
def clock(monkeypatch):
    value = [NOW]
    for module in ('gps_emi.analysis.sessions', 'gps_emi.collector'):
        monkeypatch.setattr(module + '.acquisition_now', lambda: value[0])
    monkeypatch.setattr('gps_emi.collector.configure_logging', lambda: None)
    return value


@pytest.fixture
def store(tmp_path, clock):
    return SessionStore(tmp_path / 'sessions.db', heartbeat_seconds=300)


def vehicle():
    return Vehicle('synthetic', 'TEST', NOW.replace(tzinfo=None), latitude=6.2,
                   longitude=-75.5, ignition=0, speed=0, gps_fix=0, zones=['EMI_Medellin_Taller'])


@pytest.mark.parametrize('value,seconds', [('30m',1800),('6h',21600),('24h',86400),('3d',259200),('7d',604800)])
def test_duration(value, seconds):
    assert duration_seconds(value) == seconds


@pytest.mark.parametrize('value', ['', '0h', '-1h', '1.5h', 'abc', '24', '1w', '9999999d', '1h x'])
def test_invalid_duration(value):
    with pytest.raises(ValueError):
        duration_seconds(value)


def test_lifecycle_restart_before_and_after_end(store, clock):
    assert store.status() is None
    sid = store.start_session(3600)
    with pytest.raises(ValueError):
        store.start_session(7200)
    assert store.record([vehicle()], NOW) == 1
    reopened = SessionStore(store.path)
    before = reopened.status()
    assert before['id'] == sid and before['status'] == 'COLLECTING'
    assert before['observations'] == before['vehicles'] == 1
    clock[0] += timedelta(hours=2)
    after = SessionStore(store.path).status()
    assert after['planned_end_at'] == before['planned_end_at']
    assert after['stopped_at'] == before['planned_end_at']
    assert after['status'] == 'COMPLETED'
    assert after['stop_reason'] == 'duration_elapsed'
    assert store.record([vehicle()], clock[0]) == 0


def test_manual_stop_idempotent_and_no_session_no_data(store, clock):
    assert store.record([vehicle()], NOW) == 0
    sid = store.start_session(3600)
    store.record([vehicle()], NOW)
    clock[0] += timedelta(minutes=1)
    stopped = store.status(stop=True)
    assert stopped['status'] == 'STOPPED' and stopped['stop_reason'] == 'manual'
    assert store.status(stop=True) == stopped
    assert store.record([vehicle()], NOW) == 0  # Lotes en cola se descartan tras stop.
    assert store.status()['observations'] == 1
    sid2 = store.start_session(3600)
    assert sid != sid2
    assert store.record([vehicle()], clock[0]) == 1  # Dedup aislada por sesión.


@pytest.mark.parametrize('changes', [
    {'gps_timestamp': NOW.replace(tzinfo=None)+timedelta(seconds=1)},
    {'latitude': 6.21}, {'longitude': -75.51}, {'ignition': 1}, {'speed': 0.01},
    {'gps_fix': 1}, {'zones': []}, {'zones_raw': '<B>TEST</B>'},
])
def test_conservative_dedup_and_heartbeat(store, clock, changes):
    store.start_session(3600)
    original = vehicle()
    assert store.record([original], NOW) == 1
    clock[0] += timedelta(seconds=30)
    assert store.record([original], clock[0]) == 0
    changed = replace(original, **changes)
    assert store.record([changed], clock[0]) == 1
    clock[0] += timedelta(seconds=300)
    assert SessionStore(store.path).record([changed], clock[0]) == 1


def test_migration_preserves_legacy_rows(store):
    old = ObservationStore(store.path)
    old.record([vehicle()], NOW)
    store.start_session(30)
    with sqlite3.connect(store.path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert db.execute('SELECT collection_session_id FROM gps_observations').fetchall() == [(None,)]
        names = {row[1] for row in db.execute('PRAGMA table_info(collection_sessions)')}
        assert not {'owner_id','notification_target','phone','token','cookie'} & names


def test_concurrent_start_only_one_winner(store):
    store.initialize()
    def start(_):
        try:
            return SessionStore(store.path).start_session(60)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(start, range(2)))
    assert sum(result is not None for result in results) == 1


def test_cli_synthetic_lifecycle_and_export(store, clock, tmp_path, capsys):
    prefix = ['--db', str(store.path)]
    assert main(prefix + ['status']) == 0
    assert 'No existe sesión activa' in capsys.readouterr().out
    assert main(prefix + ['start','--duration','30m']) == 0
    sid = store.status()['id']
    assert main(prefix + ['start','--duration','7d']) == 1
    assert store.record([vehicle()], NOW) == 1
    assert main(prefix + ['status']) == 0
    assert 'Observations: 1' in capsys.readouterr().out
    assert main(prefix + ['stop']) == 0
    output = tmp_path/'observations.csv'
    assert main(prefix + ['export','--session',sid,'--output',str(output)]) == 0
    with output.open(encoding='utf-8',newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]['collection_session_id'] == sid
    assert main(prefix + ['start','--duration','invalid']) == 1
    assert main(prefix + ['export','--session','missing','--output',str(tmp_path/'missing.csv')]) == 1


def test_export_filters_only_selected_session(store, clock, tmp_path):
    first = store.start_session(60)
    store.record([vehicle()], NOW)
    store.status(stop=True)
    clock[0] += timedelta(seconds=1)
    second = store.start_session(60)
    store.record([vehicle()], clock[0])
    output = tmp_path/'out.csv'
    assert export_csv(store.path, output, session_id=first) == 1
    assert first in output.read_text() and second not in output.read_text()


def test_one_acquisition_for_session_and_watches_completion_keeps_watches(store, clock):
    store.start_session(60)
    collector = SessionCollector(store)
    collector.refresh()
    source = Mock()
    source.get_vehicles.return_value = [vehicle()]
    manager = WatchManager(Mock())
    polling = FleetPolling(lambda: ScriptedSnapshots(source, utcnow=lambda: __import__('gps_emi.analysis.sessions', fromlist=['acquisition_now']).acquisition_now()), manager, collector=collector, autostart=False)
    assert publish(polling) is None  # Una sesión sola usa el coordinador existente.
    assert source.get_vehicles.call_count == 1
    polling.request_watch('owner', 'TEST', 'target')
    publish(polling)
    assert source.get_vehicles.call_count == 2
    assert manager.has_active()
    clock[0] += timedelta(seconds=61)
    collector.refresh()
    assert not collector.active
    publish(polling)
    assert source.get_vehicles.call_count == 3 and manager.has_active()
    polling.close()


def test_terminal_provider_error_does_not_spin_for_session(store):
    store.start_session(60)
    collector = SessionCollector(store)
    collector.refresh()
    source = Mock()
    source.get_vehicles.side_effect = SessionExpiredError()
    polling = FleetPolling(lambda: ScriptedSnapshots(source, utcnow=lambda: __import__('gps_emi.analysis.sessions', fromlist=['acquisition_now']).acquisition_now()), WatchManager(Mock()), collector=collector, autostart=False)
    assert publish(polling) is None
    assert not polling.active
    assert publish(polling) is None
    source.get_vehicles.assert_called_once()


def test_collector_failure_logs_once_without_sensitive_exception(store, caplog):
    collector = SessionCollector(store)
    store.status = Mock(side_effect=sqlite3.OperationalError('DO_NOT_LOG_SECRET'))
    collector.refresh()
    collector.refresh()
    assert not collector.active
    assert 'DO_NOT_LOG_SECRET' not in caplog.text
    assert caplog.text.count('state failed') == 1
    store.status = Mock(return_value=None)
    collector.refresh()
    assert 'state recovered' in caplog.text


def test_health_independent_of_broken_sqlite(store):
    from gps_emi.whatsapp.webhook import create_app
    store.status = Mock(side_effect=sqlite3.OperationalError('private'))
    collector = SessionCollector(store)
    collector.refresh()
    response = create_app(None, None).test_client().get('/health')
    assert response.status_code == 200 and response.json == {'status': 'ok'}


def test_external_stop_disables_submit_before_next_cycle(store):
    store.start_session(60)
    collector = SessionCollector(store)
    collector.refresh()
    assert collector.submit([vehicle()], NOW)
    SessionStore(store.path).status(stop=True)
    collector.refresh()
    assert not collector.submit([vehicle()], NOW)
    queued, stamp = collector.queue.get_nowait()
    assert store.record(queued, stamp) == 0
