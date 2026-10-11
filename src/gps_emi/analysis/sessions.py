"""Sesiones persistentes; ningún acceso al proveedor GPS."""
from datetime import timedelta
import logging
from queue import Empty, Full
from copy import deepcopy
import re
import time
from uuid import uuid4

from gps_emi.clock import acquisition_now
from gps_emi.observability import metrics
from .collector import ObservationStore, PassiveCollector, utc_text

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
    def _migrate_extra(self, db):
        db.execute('''CREATE TABLE IF NOT EXISTS collection_sessions (
            id TEXT PRIMARY KEY, started_at TEXT NOT NULL, planned_end_at TEXT NOT NULL,
            stopped_at TEXT, status TEXT NOT NULL,
            requested_duration_seconds INTEGER NOT NULL, created_at TEXT NOT NULL, stop_reason TEXT)''')
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_session ON collection_sessions(status) WHERE status='COLLECTING'")
        columns = {row[1] for row in db.execute('PRAGMA table_info(gps_observations)')}
        if 'collection_session_id' not in columns:
            db.execute('ALTER TABLE gps_observations ADD COLUMN collection_session_id TEXT REFERENCES collection_sessions(id)')
        db.execute('CREATE INDEX IF NOT EXISTS observations_session_vehicle ON gps_observations(collection_session_id, vehicle_id, id DESC)')
        fresh = db.execute("SELECT 1 FROM sqlite_master WHERE name='collection_observations'").fetchone() is None
        db.execute("""CREATE TABLE IF NOT EXISTS collection_observations (
            session_id TEXT NOT NULL REFERENCES collection_sessions(id),
            observation_id INTEGER NOT NULL REFERENCES gps_observations(id),
            received_at TEXT NOT NULL, PRIMARY KEY(session_id,observation_id))""")
        if fresh:
            db.execute("""INSERT OR IGNORE INTO collection_observations
                SELECT collection_session_id,id,acquired_at FROM gps_observations
                WHERE collection_session_id IS NOT NULL""")
        db.execute("""CREATE TABLE IF NOT EXISTS collection_batches (
            token TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES collection_sessions(id),
            started_at TEXT NOT NULL, acquired_at TEXT NOT NULL, admitted_at TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('admitted','written')))""")
        db.execute("""CREATE TABLE IF NOT EXISTS collection_runtime (
            session_id TEXT PRIMARY KEY REFERENCES collection_sessions(id),
            epoch TEXT NOT NULL, last_observed_at TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS collection_interruptions (
            id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES collection_sessions(id),
            last_observed_at TEXT NOT NULL, detected_at TEXT NOT NULL, reason TEXT NOT NULL)""")

    @staticmethod
    def _counts(db, session):
        return db.execute("SELECT count(*), count(DISTINCT NULLIF(o.vehicle_id,'')) FROM collection_observations c JOIN gps_observations o ON o.id=c.observation_id WHERE c.session_id=?", (session,)).fetchone()

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

    def admit(self, acquired_at, started_at, token):
        acquired, started = utc_text(acquired_at), utc_text(started_at)
        db = self._connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                existing = db.execute('SELECT session_id FROM collection_batches WHERE token=?', (token,)).fetchone()
                if existing:
                    return existing[0]
                now = utc_text(acquisition_now())
                self._expire(db, now)
                session = db.execute("""SELECT id FROM collection_sessions
                    WHERE status='COLLECTING' AND started_at<=? AND planned_end_at>?
                    AND started_at<=? AND planned_end_at>?""", (started, acquired, now, now)).fetchone()
                if session is None or acquired < started or acquired > now:
                    return None
                db.execute("INSERT INTO collection_batches VALUES (?,?,?,?,?,'admitted')",
                           (token, session[0], started, acquired, now))
                return session[0]
        finally:
            db.close()

    def record(self, vehicles, acquired_at, *, started_at=None, token=None):
        token = token or uuid4().hex
        if self.admit(acquired_at, started_at or acquired_at, token) is None:
            return 0
        db = self._connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                sid, acquired, state = db.execute(
                    'SELECT session_id,acquired_at,state FROM collection_batches WHERE token=?', (token,)).fetchone()
                if state == 'written':
                    return 0
                # Admission is durable: stop/expiry cannot revoke a begun write.
                inserted = self._write(db, vehicles, acquired, sid)
                db.execute("UPDATE collection_batches SET state='written' WHERE token=?", (token,))
            metrics.increment(observations_written=inserted)
            return inserted
        finally:
            db.close()

    def checkpoint(self, epoch, session, now=None):
        if session is None:
            return
        now = utc_text(now or acquisition_now())
        db = self._connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                old = db.execute('SELECT epoch,last_observed_at FROM collection_runtime WHERE session_id=?', (session['id'],)).fetchone()
                lower = old[1] if old else session['started_at']
                upper = min(now, session['stopped_at'] or session['planned_end_at'])
                if (old is None or old[0] != epoch) and lower < upper:
                    db.execute('INSERT INTO collection_interruptions(session_id,last_observed_at,detected_at,reason) VALUES (?,?,?,?)',
                               (session['id'], lower, upper, 'restart_window' if old else 'first_attachment_window'))
                db.execute('INSERT INTO collection_runtime VALUES (?,?,?) ON CONFLICT(session_id) DO UPDATE SET epoch=excluded.epoch,last_observed_at=excluded.last_observed_at',
                           (session['id'], epoch, now))
        finally:
            db.close()


class SessionCollector(PassiveCollector):
    def __init__(self, store, **kwargs):
        super().__init__(store, **kwargs)
        self.active_session = None
        self.epoch = uuid4().hex
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
            self.store.checkpoint(self.epoch, session)
            old = self.active_session
            self.active_session = session if session and session['status'] == 'COLLECTING' else None
            if (old or {}).get('id') != (self.active_session or {}).get('id'):
                logger.info('collection observed status=%s session_id=%s', session['status'] if session else 'NONE', session['id'] if session else 'NONE')
            metrics.update(collection_session=session['status'] if session else 'NONE')
            self.recovered('state')
        except Exception:
            self.active_session = None
            self.failed('state')

    def submit(self, vehicles, acquired_at, *, started_at=None):
        with self.lock:
            if self.stopping.is_set() or not self.active:
                return False
            try:
                self.queue.put_nowait((deepcopy(tuple(vehicles)), acquired_at,
                                       started_at or acquired_at, uuid4().hex))
                return True
            except Full:
                metrics.increment(dropped_snapshots=1)
                logger.warning('Collector saturado; snapshot omitido.')
                return False

    def _run(self):
        next_refresh = 0
        while not self.stopping.is_set() or not self.queue.empty():
            if time.monotonic() >= next_refresh:
                self.refresh()
                next_refresh = time.monotonic() + 1
            try:
                vehicles, acquired, started, token = self.queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                for attempt in range(2):
                    try:
                        self.store.record(vehicles, acquired, started_at=started, token=token)
                        self.recovered('write')
                        break
                    except Exception:
                        if attempt:
                            raise
                        self.failed('write')
            except Exception:
                self.failed('write')
            finally:
                self.queue.task_done()
