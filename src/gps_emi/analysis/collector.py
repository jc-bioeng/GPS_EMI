"""Persistencia pasiva de una lista explícita de campos de Vehicle."""
from copy import deepcopy
from hashlib import sha256
import json
import logging
import math
import os
from pathlib import Path
from queue import Queue, Full, Empty
from threading import Event, Lock, Thread
from gps_emi.database import connect_database, utc_text

logger = logging.getLogger(__name__)
DEFAULT_DB = 'data/gps_observations.db'
DATA_COLUMNS = ('vehicle_id', 'mobile_number', 'plate', 'vehicle_name_raw',
                'vehicle_license_raw', 'gps_reported_at', 'latitude', 'longitude',
                'speed', 'ignition', 'gps_fix', 'zones', 'zones_raw', 'reported_location')
EXPORT_COLUMNS = ('id', 'acquired_at') + DATA_COLUMNS
METADATA_COLUMNS = ('fleet_name', 'fleet_raw', 'gps_original', 'server_original',
                    'provider_record_id', 'provenance', 'gps_instant', 'historical', 'timestamp_collision')


def observation_key(values, source, instant):
    # Labels/fleet/server receipt/Id are not GPS identity. Preserve them on first
    # receipt, but never create another GPS row merely because they changed.
    core = (source, values[0], instant, *values[6:])
    return sha256(json_value(core).encode('utf-8')).hexdigest()



def json_value(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def observation(vehicle):
    return (vehicle.vehid, vehicle.mobile_number, vehicle.plate,
            vehicle.vehicle_name_raw, vehicle.vehicle_license_raw,
            vehicle.gps_timestamp.isoformat() if vehicle.gps_timestamp else None,
            vehicle.latitude, vehicle.longitude, vehicle.speed,
            json_value(vehicle.ignition), json_value(vehicle.gps_fix),
            json_value(vehicle.zones), vehicle.zones_raw, vehicle.location)


class ObservationStore:
    """Una conexión por transacción; sin conexiones compartidas entre threads."""

    def __init__(self, path=DEFAULT_DB, heartbeat_seconds=300):
        if not math.isfinite(heartbeat_seconds) or heartbeat_seconds <= 0:
            raise ValueError('Heartbeat inválido.')
        self.path = Path(path)
        self.heartbeat_seconds = heartbeat_seconds

    def _connect(self):
        db = connect_database(self.path)
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                version = db.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0, 1, 2, 3):
                    raise ValueError('Versión de esquema no soportada.')
                db.execute("""CREATE TABLE IF NOT EXISTS gps_observations (
                    id INTEGER PRIMARY KEY, acquired_at TEXT NOT NULL,
                    vehicle_id TEXT, mobile_number TEXT, plate TEXT,
                    vehicle_name_raw TEXT, vehicle_license_raw TEXT,
                    gps_reported_at TEXT, latitude, longitude, speed,
                    ignition TEXT, gps_fix TEXT, zones TEXT, zones_raw TEXT,
                    reported_location TEXT, fingerprint TEXT NOT NULL)""")
                db.execute('CREATE INDEX IF NOT EXISTS observations_vehicle ON gps_observations(vehicle_id, id DESC)')
                db.execute('CREATE INDEX IF NOT EXISTS observations_acquired ON gps_observations(acquired_at)')
                columns = {r[1] for r in db.execute('PRAGMA table_info(gps_observations)')}
                for name in METADATA_COLUMNS:
                    if name not in columns:
                        db.execute(f'ALTER TABLE gps_observations ADD COLUMN {name} ' +
                                   ('INTEGER' if name in ('historical', 'timestamp_collision') else 'TEXT'))
                db.execute("""CREATE TABLE IF NOT EXISTS observation_keys (
                    key TEXT PRIMARY KEY, observation_id INTEGER NOT NULL REFERENCES gps_observations(id),
                    source TEXT NOT NULL, vehicle_id TEXT NOT NULL, gps_instant TEXT NOT NULL)""")
                db.execute('CREATE INDEX IF NOT EXISTS observation_time ON observation_keys(source,vehicle_id,gps_instant)')
                # Add keys, not fabricated metadata or rewritten historical rows.
                if version < 3:
                    for row in db.execute('SELECT id,' + ','.join(DATA_COLUMNS) + ' FROM gps_observations ORDER BY id'):
                        oid, values = row[0], row[1:]
                        if values[0] and values[5]:
                            key = observation_key(values, 'legacy', values[5])
                            db.execute('INSERT OR IGNORE INTO observation_keys VALUES (?,?,?,?,?)',
                                       (key, oid, 'legacy', values[0], values[5]))
                self._migrate_extra(db)
                db.execute('PRAGMA user_version=3')
            return db
        except Exception:
            db.close()
            raise

    def _migrate_extra(self, db):
        pass

    def initialize(self):
        self._connect().close()

    def _write(self, db, vehicles, acquired, session_id=None):
        inserted = 0
        for vehicle in vehicles:
            values = observation(vehicle)
            if not vehicle.vehid or not vehicle.gps_timestamp:
                continue  # No invented identity or GPS observation.
            source = vehicle.provenance or 'legacy'
            instant = vehicle.gps_instant or values[5]
            key = observation_key(values, source, instant)
            found = db.execute('SELECT observation_id FROM observation_keys WHERE key=?', (key,)).fetchone()
            if found:
                oid = found[0]
            else:
                latest = db.execute('SELECT max(gps_instant) FROM observation_keys WHERE source=? AND vehicle_id=?',
                                    (source, vehicle.vehid)).fetchone()[0]
                collision = db.execute('SELECT 1 FROM observation_keys WHERE source=? AND vehicle_id=? AND gps_instant=?',
                                       (source, vehicle.vehid, instant)).fetchone() is not None
                metadata = tuple(getattr(vehicle, name) for name in METADATA_COLUMNS[:-2]) + (
                    int(latest is not None and instant < latest), int(collision))
                columns = ('acquired_at',) + DATA_COLUMNS + ('fingerprint',) + METADATA_COLUMNS
                data = (acquired,) + values + (key,) + metadata
                if session_id is not None:
                    columns += ('collection_session_id',)
                    data += (session_id,)
                oid = db.execute(f'INSERT INTO gps_observations ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})', data).lastrowid
                db.execute('INSERT INTO observation_keys VALUES (?,?,?,?,?)', (key, oid, source, vehicle.vehid, instant))
                inserted += 1
            if session_id is not None:
                db.execute('INSERT OR IGNORE INTO collection_observations VALUES (?,?,?)', (session_id, oid, acquired))
        return inserted

    def record(self, vehicles, acquired_at):
        acquired = utc_text(acquired_at)
        db = self._connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                return self._write(db, vehicles, acquired)
        finally:
            db.close()


class PassiveCollector:
    """Cola limitada: saturación o escritura fallida pierde muestras, no vigilancias."""

    def __init__(self, store, *, capacity=32):
        self.store = store
        self.queue = Queue(maxsize=capacity)
        self.stopping = Event()
        self.lock = Lock()
        self.thread = Thread(target=self._run, name='gps-emi-collector', daemon=True)

    def start(self):
        self.thread.start()

    def submit(self, vehicles, acquired_at, *, started_at=None):
        with self.lock:
            if self.stopping.is_set():
                return False
            try:
                self.queue.put_nowait((deepcopy(tuple(vehicles)), acquired_at))
                return True
            except Full:
                logger.warning('Collector saturado; snapshot omitido.')
                return False

    def _run(self):
        try:
            self.store.initialize()
        except Exception:
            logger.warning('Collector: inicialización fallida; se reintentará al recibir un snapshot.')
        while not self.stopping.is_set() or not self.queue.empty():
            try:
                vehicles, acquired_at = self.queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                self.store.record(vehicles, acquired_at)
            except Exception:
                # No registrar excepciones, rutas, filas ni datos del proveedor.
                logger.warning('Collector: escritura fallida; snapshot omitido, operación conservada.')
            finally:
                self.queue.task_done()

    def close(self, timeout=2):
        with self.lock:
            self.stopping.set()
        if self.thread.ident is not None:
            self.thread.join(timeout)
        complete = not self.thread.is_alive()
        if not complete:
            logger.warning('Collector: cierre acotado; pueden quedar muestras pendientes.')
        return complete


def start_collector():
    try:
        from .sessions import SessionCollector, SessionStore
        collector = SessionCollector(SessionStore(
            os.environ.get('GPS_EMI_DATA_DB', DEFAULT_DB),
            float(os.environ.get('GPS_EMI_COLLECTION_HEARTBEAT_SECONDS',
                                 os.environ.get('GPS_EMI_DATA_HEARTBEAT_SECONDS', '300')))))
        collector.start()
        return collector
    except Exception:
        logger.warning('Collector deshabilitado por configuración o arranque inválido; operación conservada.')
        return None
