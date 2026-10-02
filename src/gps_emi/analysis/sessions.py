"""Sesiones persistentes; ningún acceso al proveedor GPS."""
from datetime import datetime, timedelta
from hashlib import sha256
import logging
from queue import Empty
import re
import time
from uuid import uuid4

from gps_emi.clock import acquisition_now
from gps_emi.observability import metrics
from .collector import ObservationStore, PassiveCollector, utc_text, observation, json_value, DATA_COLUMNS

logger = logging.getLogger(__name__)


def duration_seconds(value):
    match = re.fullmatch(r'([1-9][0-9]{0,6})([smhd])', value)
    if not match:
        raise ValueError('Duración inválida: use 30m, 6h, 24h, 3d o 7d.')
    seconds = int(match[1]) * {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[match[2]]
    if seconds > 3650 * 86400:
        raise ValueError('Duración demasiado larga.')
    return seconds


class SessionStore(ObservationStore):
    def _connect(self):
        db = super()._connect()
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('''CREATE TABLE IF NOT EXISTS collection_sessions (
                    id TEXT PRIMARY KEY, started_at TEXT NOT NULL, planned_end_at TEXT NOT NULL,
                    stopped_at TEXT, status TEXT NOT NULL,
                    requested_duration_seconds INTEGER NOT NULL, created_at TEXT NOT NULL, stop_reason TEXT)''')
                db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_session ON collection_sessions(status) WHERE status='COLLECTING'")
                columns = {row[1] for row in db.execute('PRAGMA table_info(gps_observations)')}
                if 'collection_session_id' not in columns:
                    db.execute('ALTER TABLE gps_observations ADD COLUMN collection_session_id TEXT REFERENCES collection_sessions(id)')
                db.execute('CREATE INDEX IF NOT EXISTS observations_session_vehicle ON gps_observations(collection_session_id, vehicle_id, id DESC)')
                db.execute('PRAGMA user_version=2')
            return db
        except Exception:
            db.close()
            raise

    @staticmethod
    def _counts(db, session):
        return db.execute('SELECT count(*), count(DISTINCT NULLIF(vehicle_id,\'\')) FROM gps_observations WHERE collection_session_id=?', (session,)).fetchone()

    def _expire(self, db, now):
        expired = db.execute("SELECT id, requested_duration_seconds FROM collection_sessions WHERE status='COLLECTING' AND planned_end_at<=?", (now,)).fetchall()
        db.execute("UPDATE collection_sessions SET status='COMPLETED', stopped_at=planned_end_at, stop_reason='duration_elapsed' WHERE status='COLLECTING' AND planned_end_at<=?", (now,))
        for sid, duration in expired:
            count, vehicles = self._counts(db, sid)
            logger.info('collection completed session_id=%s duration=%s observations=%s vehicles=%s', sid, duration, count, vehicles)

    def start_session(self, seconds, now=None):
        if not isinstance(seconds, int) or not 0 < seconds <= 3650 * 86400:
            raise ValueError('Duración inválida.')
        now = now or acquisition_now()
        started, end = utc_text(now), utc_text(now + timedelta(seconds=seconds))
        db = self._connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                self._expire(db, started)
                if db.execute("SELECT 1 FROM collection_sessions WHERE status='COLLECTING'").fetchone():
                    raise ValueError('Ya existe una sesión activa; no se reinició su duración.')
                sid = uuid4().hex
                db.execute('INSERT INTO collection_sessions VALUES (?,?,?,NULL,?,?,?,NULL)',
                           (sid, started, end, 'COLLECTING', seconds, started))
            logger.info('collection started session_id=%s duration=%s planned_end_at=%s', sid, seconds, end)
            return sid
        finally:
            db.close()

    def status(self, now=None, *, stop=False):
        now = utc_text(now or acquisition_now())
        db = self._connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                self._expire(db, now)
                if stop:
                    sid = db.execute("SELECT id FROM collection_sessions WHERE status='COLLECTING'").fetchone()
                    db.execute("UPDATE collection_sessions SET status='STOPPED', stopped_at=?, stop_reason='manual' WHERE status='COLLECTING'", (now,))
                    if sid:
                        logger.info('collection stopped session_id=%s reason=manual observations=%s vehicles=%s', sid[0], *self._counts(db, sid[0]))
                cursor = db.execute('SELECT * FROM collection_sessions ORDER BY created_at DESC, rowid DESC LIMIT 1')
                row = cursor.fetchone()
                if row is None:
                    return None
                result = dict(zip([column[0] for column in cursor.description], row))
                result['observations'], result['vehicles'] = self._counts(db, result['id'])
                return result
        finally:
            db.close()

    def record(self, vehicles, acquired_at):
        acquired = utc_text(acquired_at)
        db = self._connect()
        inserted = 0
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                self._expire(db, utc_text(acquisition_now()))
                session = db.execute("SELECT id FROM collection_sessions WHERE status='COLLECTING' AND started_at<=? AND planned_end_at>?", (acquired, acquired)).fetchone()
                if session is None:
                    logger.debug('collection snapshot ignored reason=no_active_session')
                    return 0
                for vehicle in vehicles:
                    values = observation(vehicle)
                    fingerprint = sha256(json_value(values).encode('utf-8')).hexdigest()
                    last = db.execute('SELECT acquired_at, fingerprint FROM gps_observations WHERE collection_session_id=? AND vehicle_id=? ORDER BY id DESC LIMIT 1',
                                      (session[0], vehicle.vehid)).fetchone() if vehicle.vehid else None
                    if last and last[1] == fingerprint:
                        elapsed = (datetime.fromisoformat(acquired) - datetime.fromisoformat(last[0])).total_seconds()
                        if 0 <= elapsed < self.heartbeat_seconds:
                            logger.debug('collection observation ignored reason=duplicate')
                            continue
                    columns = ('acquired_at',) + DATA_COLUMNS + ('fingerprint', 'collection_session_id')
                    db.execute(f'INSERT INTO gps_observations ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})', (acquired,) + values + (fingerprint, session[0]))
                    inserted += 1
            metrics.increment(observations_written=inserted)
            return inserted
        finally:
            db.close()


class SessionCollector(PassiveCollector):
    def __init__(self, store, **kwargs):
        super().__init__(store, **kwargs)
        self.active_session = None
        self.failures = set()
        self.failure_counts = {}

    def failed(self, kind):
        metrics.increment(collector_errors=1)
        self.failure_counts[kind] = self.failure_counts.get(kind, 0) + 1
        if kind not in self.failures:
            logger.warning('collection %s failed; operational service continues', kind)
            self.failures.add(kind)
        elif self.failure_counts[kind] == 3:
            logger.error('collection %s persistently unavailable; inspect database access', kind)

    def recovered(self, kind):
        if kind in self.failures:
            logger.info('collection %s recovered', kind)
            self.failures.remove(kind)
        self.failure_counts.pop(kind, None)

    @property
    def active(self):
        session = self.active_session
        return bool(session and utc_text(acquisition_now()) < session['planned_end_at'])

    def refresh(self):
        try:
            session = self.store.status()
            old = self.active_session
            self.active_session = session if session and session['status'] == 'COLLECTING' else None
            if (old or {}).get('id') != (self.active_session or {}).get('id'):
                logger.info('collection observed status=%s session_id=%s', session['status'] if session else 'NONE', session['id'] if session else 'NONE')
            metrics.update(collection_session=session['status'] if session else 'NONE')
            self.recovered('state')
        except Exception:
            self.active_session = None
            self.failed('state')

    def submit(self, vehicles, acquired_at):
        if not self.active:
            return False
        accepted = super().submit(vehicles, acquired_at)
        if not accepted:
            metrics.increment(dropped_snapshots=1)
        return accepted

    def _run(self):
        next_refresh = 0
        while not self.stopping.is_set() or not self.queue.empty():
            if time.monotonic() >= next_refresh:
                self.refresh()
                next_refresh = time.monotonic() + 1
            try:
                vehicles, acquired = self.queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                self.store.record(vehicles, acquired)
                self.recovered('write')
            except Exception:
                self.failed('write')
            finally:
                self.queue.task_done()
