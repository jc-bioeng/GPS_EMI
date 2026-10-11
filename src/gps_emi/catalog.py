"""National identity/presence catalog. Consumes publications, never performs HTTP."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from threading import RLock

from gps_emi.database import connect_database, utc_text
from gps_emi.models import normalize_plate

MEDELLIN_FLEETS = frozenset(('Ambulancias Medellin', 'Ambulancias Medellín'))


@dataclass(frozen=True, repr=False)
class Identity:
    vehicle_id: str
    plate: str | None
    mobile_number: str | None
    fleet_name: str | None


def identities(batch, mapping=None):
    """Presence needs an unambiguous ID, independently of GPS validity."""
    counts = Counter(row.vehicle_id for row in batch.records)
    diagnosed = defaultdict(list)
    for diagnostic in batch.diagnostics:
        diagnosed[diagnostic.row].append(diagnostic)
    result = []
    for index, row in enumerate(batch.records, 1):
        issues = (*row.diagnostics, *diagnosed[index], *diagnosed[None])
        def known(field):
            return (row.raw.get(field) is not None and
                    not any(d.field in (field, 'Table', None) for d in issues))
        if (not row.vehicle_id or counts[row.vehicle_id] != 1 or
                row.vehicle_id in batch.duplicate_ids or not known('VEH_ID')):
            continue
        plate = normalize_plate(row.raw[mapping.plate_field]) if mapping and known(mapping.plate_field) else None
        mobile = row.raw[mapping.mobile_field].strip() if mapping and known(mapping.mobile_field) else None
        fleet = row.fleet_name if known('fltName') and row.fleet_name else None
        result.append(Identity(row.vehicle_id, plate, mobile, fleet))
    return tuple(result)


def absence_eligible(batch, present):
    # TEC-01 approved operational criterion, NOT proof of complete coverage.
    return bool(batch.records) and not batch.diagnostics and not batch.duplicate_ids and (
        len(present) == len(batch.records) and all(item.fleet_name for item in present))


@dataclass(frozen=True, repr=False)
class CatalogEntry:
    vehicle_id: str
    plate: str | None
    mobile_number: str | None
    fleet_name: str | None
    first_seen: str
    last_seen: str
    presence: str
    disappeared_at: str | None
    reappeared_at: str | None


@dataclass(frozen=True, repr=False)
class CatalogView:
    entries: tuple[CatalogEntry, ...]
    absence_eligible: bool


class CatalogStore:
    """One serialized writer per authority; SQLite also serializes campaign writes.

    Provisional misses live only in this authority. Restart/error resets them.
    Acquisitions/events have durable unique keys to make replay idempotent.
    """
    def __init__(self, path):
        self.path = path
        self.lock = RLock()
        self._misses = {}

    def _connect(self):
        db = connect_database(self.path)
        try:
            if db.execute('PRAGMA user_version').fetchone()[0] not in (0, 1, 2, 3):
                raise ValueError('Versión de esquema no soportada.')
            with db:
                db.execute('BEGIN IMMEDIATE')
                # Independent additive schema: do not rewrite collector user_version.
                db.execute('''CREATE TABLE IF NOT EXISTS catalog_schema (
                    version INTEGER PRIMARY KEY CHECK(version=1))''')
                if any(row[0] != 1 for row in db.execute('SELECT version FROM catalog_schema')):
                    raise ValueError('Versión de catálogo no soportada.')
                db.execute('INSERT OR IGNORE INTO catalog_schema VALUES (1)')
                db.execute('''CREATE TABLE IF NOT EXISTS catalog_vehicles (
                    vehicle_id TEXT PRIMARY KEY, plate TEXT, mobile_number TEXT, fleet_name TEXT,
                    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                    presence TEXT NOT NULL CHECK(presence IN ('present','disappeared')),
                    disappeared_at TEXT, reappeared_at TEXT)''')
                db.execute('''CREATE TABLE IF NOT EXISTS catalog_acquisitions (
                    epoch TEXT NOT NULL, version INTEGER NOT NULL, acquired_at TEXT NOT NULL,
                    absence_eligible INTEGER NOT NULL, PRIMARY KEY(epoch,version))''')
                db.execute('''CREATE TABLE IF NOT EXISTS catalog_events (
                    id INTEGER PRIMARY KEY, vehicle_id TEXT NOT NULL REFERENCES catalog_vehicles(vehicle_id),
                    kind TEXT NOT NULL CHECK(kind IN ('disappearance','reappearance')),
                    occurred_at TEXT NOT NULL, epoch TEXT NOT NULL, version INTEGER NOT NULL,
                    UNIQUE(vehicle_id,kind,epoch,version))''')
            return db
        except Exception:
            db.close()
            raise

    def initialize(self):
        with self.lock:
            self._connect().close()
            self._misses.clear()

    def interrupt(self):
        with self.lock:
            self._misses.clear()

    @staticmethod
    def _entries(db):
        return tuple(CatalogEntry(*r) for r in db.execute(
            'SELECT vehicle_id,plate,mobile_number,fleet_name,first_seen,last_seen,presence,disappeared_at,reappeared_at '
            'FROM catalog_vehicles ORDER BY vehicle_id'))

    def apply(self, snapshot):
        eligible = absence_eligible(snapshot.result, snapshot.identities)
        now = utc_text(snapshot.acquired_at)
        key = (snapshot.epoch, snapshot.version)
        with self.lock:
            db = None
            try:
                db = self._connect()
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    seen = db.execute('SELECT absence_eligible FROM catalog_acquisitions WHERE epoch=? AND version=?', key).fetchone()
                    if seen is not None:
                        return CatalogView(self._entries(db), bool(seen[0]))
                    previous = {v.vehicle_id: v for v in self._entries(db)}
                    present = {v.vehicle_id: v for v in snapshot.identities}
                    misses = dict(self._misses) if eligible else {}
                    for identity in present.values():
                        old = previous.get(identity.vehicle_id)
                        returned = old is not None and old.presence == 'disappeared'
                        db.execute('''INSERT INTO catalog_vehicles VALUES (?,?,?,?,?,?,'present',NULL,?)
                            ON CONFLICT(vehicle_id) DO UPDATE SET
                            plate=COALESCE(excluded.plate,catalog_vehicles.plate),
                            mobile_number=COALESCE(excluded.mobile_number,catalog_vehicles.mobile_number),
                            fleet_name=COALESCE(excluded.fleet_name,catalog_vehicles.fleet_name),
                            last_seen=excluded.last_seen, presence='present',
                            reappeared_at=COALESCE(excluded.reappeared_at,catalog_vehicles.reappeared_at)''',
                            (identity.vehicle_id, identity.plate, identity.mobile_number, identity.fleet_name,
                             now, now, now if returned else None))
                        misses.pop(identity.vehicle_id, None)
                        if returned:
                            db.execute('INSERT INTO catalog_events(vehicle_id,kind,occurred_at,epoch,version) VALUES (?,\'reappearance\',?,?,?)',
                                       (identity.vehicle_id, now, *key))
                    if eligible:
                        for vid, old in previous.items():
                            if vid in present or old.presence == 'disappeared':
                                continue
                            misses[vid] = misses.get(vid, 0)+1
                            if misses[vid] == 3:
                                db.execute("UPDATE catalog_vehicles SET presence='disappeared', disappeared_at=? WHERE vehicle_id=?", (now, vid))
                                db.execute('INSERT INTO catalog_events(vehicle_id,kind,occurred_at,epoch,version) VALUES (?,\'disappearance\',?,?,?)', (vid, now, *key))
                    db.execute('INSERT INTO catalog_acquisitions VALUES (?,?,?,?)', (*key, now, int(eligible)))
                    view = CatalogView(self._entries(db), eligible)
                self._misses = misses  # Advance only after commit.
                return view
            except Exception:
                self._misses.clear()
                raise
            finally:
                if db is not None:
                    db.close()
