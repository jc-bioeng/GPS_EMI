"""Persistencia pasiva de una lista explícita de campos de Vehicle."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import math
import os
from pathlib import Path
from queue import Queue, Full, Empty
import sqlite3
from threading import Event, Lock, Thread
from gps_emi.database import connect_database, utc_text

logger = logging.getLogger(__name__)
DEFAULT_DB = 'data/gps_observations.db'
DATA_COLUMNS = ('vehicle_id', 'mobile_number', 'plate', 'vehicle_name_raw',
                'vehicle_license_raw', 'gps_reported_at', 'latitude', 'longitude',
                'speed', 'ignition', 'gps_fix', 'zones', 'zones_raw', 'reported_location')
EXPORT_COLUMNS = ('id', 'acquired_at') + DATA_COLUMNS


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
        connection = connect_database(self.path)
        try:
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError('Versión de esquema no soportada.')
            connection.execute('''CREATE TABLE IF NOT EXISTS gps_observations (
                id INTEGER PRIMARY KEY, acquired_at TEXT NOT NULL,
                vehicle_id TEXT, mobile_number TEXT, plate TEXT,
                vehicle_name_raw TEXT, vehicle_license_raw TEXT,
                gps_reported_at TEXT, latitude, longitude, speed,
                ignition TEXT, gps_fix TEXT, zones TEXT, zones_raw TEXT,
                reported_location TEXT, fingerprint TEXT NOT NULL)''')
            connection.execute('CREATE INDEX IF NOT EXISTS observations_vehicle ON gps_observations(vehicle_id, id DESC)')
            connection.execute('CREATE INDEX IF NOT EXISTS observations_acquired ON gps_observations(acquired_at)')
            if version == 0:
                connection.execute('PRAGMA user_version=1')
            connection.commit()
            return connection
        except Exception:
            connection.close()
            raise

    def initialize(self):
        self._connect().close()

    def record(self, vehicles, acquired_at):
        acquired = utc_text(acquired_at)
        connection = self._connect()
        inserted = 0
        try:
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                for vehicle in vehicles:
                    values = observation(vehicle)
                    fingerprint = sha256(json_value(values).encode('utf-8')).hexdigest()
                    last = connection.execute(
                        'SELECT acquired_at, fingerprint FROM gps_observations WHERE vehicle_id=? ORDER BY id DESC LIMIT 1',
                        (vehicle.vehid,)).fetchone() if vehicle.vehid else None
                    if last and last[1] == fingerprint:
                        elapsed = (datetime.fromisoformat(acquired) - datetime.fromisoformat(last[0])).total_seconds()
                        if 0 <= elapsed < self.heartbeat_seconds:
                            continue
                    columns = ('acquired_at',) + DATA_COLUMNS + ('fingerprint',)
                    connection.execute(f'INSERT INTO gps_observations ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',
                                       (acquired,) + values + (fingerprint,))
                    inserted += 1
            return inserted
        finally:
            connection.close()


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

    def submit(self, vehicles, acquired_at):
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
