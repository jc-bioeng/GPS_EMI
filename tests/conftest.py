import pytest
import requests
from pathlib import Path


@pytest.fixture
def observed_amb20_payload():
    """Solo los cuatro valores no sensibles de la validación manual del usuario."""
    return (Path(__file__).parent / "fixtures" / "emi_amb20.json").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Las pruebas no permiten conexiones de red")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.delenv("GPSPACE_COOKIE", raising=False)
    monkeypatch.delenv("GPSPACE_CONTENT_TYPE", raising=False)
    monkeypatch.setattr("gps_emi.cli.load_dotenv", lambda **kwargs: None)
