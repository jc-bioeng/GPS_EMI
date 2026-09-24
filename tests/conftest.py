import pytest
import requests
from pathlib import Path
from datetime import datetime
import logging
import socket
import time
import json


@pytest.fixture
def observed_amb20_payload():
    """Solo los cuatro valores no sensibles de la validación manual del usuario."""
    return (Path(__file__).parent / "fixtures" / "emi_amb20.json").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def offline(monkeypatch, caplog):
    def forbidden(*args, **kwargs):
        pytest.fail("Las pruebas no permiten conexiones de red ni esperas reales")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(time, "sleep", forbidden)
    # El servidor simulado nunca inicia persistencia local real.
    monkeypatch.setattr('gps_emi.whatsapp.server.start_collector', lambda: None)
    monkeypatch.setattr('gps_emi.analysis.collector.start_collector', lambda: None)
    monkeypatch.delenv("GPSPACE_COOKIE", raising=False)
    monkeypatch.delenv("GPSPACE_CONTENT_TYPE", raising=False)
    # Solo datos sintéticos; nunca heredar sesión/estado reales de la máquina.
    monkeypatch.setenv("GPSPACE_SESSION_INFO", json.dumps({"UID": "synthetic-user", "UNAME": "TEST_KEY"}))
    monkeypatch.setenv("GPSPACE_LOADDATALOG_STATE", json.dumps({
        "intLastUpdate": 0, "intTimer": 7, "strMobiles": "", "intConsoleType": 2,
        "idFleet": "synthetic-fleet", "intFrom": 3, "strOriginQuery": "synthetic-origin",
    }))
    monkeypatch.setattr("gps_emi.cli.load_dotenv", lambda **kwargs: None)
    monkeypatch.setattr("gps_emi.cli.configure_logging", lambda level: None)
    monkeypatch.setattr("gps_emi.monitoring.runner.local_now", lambda: datetime(2026, 9, 17, 12, 35))
    caplog.set_level(logging.INFO, logger="gps_emi")
