"""Explicit process lifetime and host-local exclusion, shared by CLI/server."""
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
from threading import Lock

from gps_emi.acquisition import AcquisitionConfig, Coordinator, LabelMapping, LegacyAcquisition, SnapshotSource
from gps_emi.errors import AcquisitionError
from gps_emi.providers.widetech_official import OfficialConfig, OfficialWideTechClient


class AuthorityBusy(AcquisitionError):
    public_message = "Ya existe una autoridad GPS en esta instalación o no se puede reservar su exclusión."


class HostLease:
    """Advisory OS lock; never unlink the inode used by other processes.

    Both entrypoints must use the same installation state directory. No claim
    is made about other installations, OS users, containers or remote hosts.
    Only a UTC permit deadline is persisted, never locations or credentials.
    """
    def __init__(self, path):
        self.file = None
        self.deadline = None
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            stream = open(path, 'a+b')
        except OSError:
            raise AuthorityBusy() from None
        try:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b' ')
                stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise AuthorityBusy() from None
        self.file = stream
        try:
            stream.seek(1)
            stored = stream.read()
            if stored:
                self.deadline = datetime.fromisoformat(json.loads(stored)['next_allowed_at'])
                if self.deadline.tzinfo is None:
                    raise ValueError()
        except Exception:
            self.close()
            raise AuthorityBusy() from None  # Corrupt protection fails closed.

    def remaining(self, now):
        return max(0, (self.deadline-now).total_seconds()) if self.deadline else 0

    def reserve(self, now, seconds):
        deadline = now + timedelta(seconds=seconds)
        self.deadline = max(self.deadline, deadline) if self.deadline else deadline
        data = json.dumps({'next_allowed_at': self.deadline.astimezone(timezone.utc).isoformat()}).encode()
        self.file.seek(1)
        self.file.truncate()
        self.file.write(data)
        self.file.flush()
        os.fsync(self.file.fileno())

    def close(self):
        if self.file is not None:
            self.file.close()  # OS releases the byte/flock lock, also on process exit.
            self.file = None


_current = None
_guard = Lock()


def current_source():
    with _guard:
        if _current is None:
            raise AcquisitionError('No hay autoridad de adquisición configurada.')
        return _current.source


def default_lock_path():
    """One configured location; permission errors must never select a fallback."""
    configured = os.getenv('GPS_EMI_STATE_DIR')
    if configured is not None:
        directory = Path(configured)
        if not configured.strip() or not directory.is_absolute():
            raise ValueError('GPS_EMI_STATE_DIR debe ser una ruta absoluta.')
    elif os.name == 'nt':
        directory = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'GPS_EMI'
    else:
        directory = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state') / 'gps-emi'
    if not directory.is_absolute():
        raise ValueError('El directorio de estado debe ser una ruta absoluta.')
    return directory / 'acquisition.lock'


class AcquisitionRuntime:
    def __init__(self, *, official=False, interval=30, max_backoff=300,
                 source=None, mapping=None, lock_path=None, catalog=None):
        global _current
        if not math.isfinite(max_backoff) or max_backoff <= 0:
            raise ValueError('Backoff de adquisición inválido.')
        config = AcquisitionConfig(interval=interval, max_backoff=max(interval, max_backoff))
        if source is None:
            if official:
                mapping = LabelMapping(os.getenv('WIDETECH_PLATE_FIELD', ''), os.getenv('WIDETECH_MOBILE_FIELD', ''))
                source = OfficialWideTechClient(OfficialConfig(
                    os.getenv('WIDETECH_LOGIN', ''), os.getenv('WIDETECH_PASSWORD', ''),
                    timezone_name=os.getenv('WIDETECH_TIMEZONE', 'America/Bogota')))
            else:
                from gps_emi.providers.widetech import LegacyWideTechTransport
                source = LegacyAcquisition(LegacyWideTechTransport())
        with _guard:
            if _current is not None:
                raise AuthorityBusy()
            lease = HostLease(lock_path or default_lock_path())
            try:
                if official and catalog is None:
                    from gps_emi.catalog import CatalogStore
                    from gps_emi.analysis.collector import DEFAULT_DB
                    catalog = CatalogStore(os.environ.get('GPS_EMI_DATA_DB', DEFAULT_DB))
                if catalog is not None:
                    catalog.initialize()
                self.coordinator = Coordinator(source, config, lease=lease, catalog=catalog, mapping=mapping)
                self.source = SnapshotSource(self.coordinator, mapping)
            except BaseException:
                lease.close()
                raise
            _current = self

    def start(self):
        self.coordinator.start()

    def request_stop(self):
        self.coordinator.request_stop()

    def close(self, timeout=2):
        global _current
        closed = self.coordinator.close(timeout)
        with _guard:
            if _current is self and closed:
                _current = None
        return closed
