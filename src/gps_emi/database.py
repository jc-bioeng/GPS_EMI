"""Shared SQLite connection policy; domain migrations remain with their stores."""
from datetime import timezone
from pathlib import Path
import sqlite3


def connect_database(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=0.25)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA foreign_keys=ON')
        return db
    except Exception:
        db.close()
        raise


def utc_text(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Se requiere timestamp con offset.')
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds')
