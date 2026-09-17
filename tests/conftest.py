import pytest
import requests


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Las pruebas no permiten conexiones de red")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.delenv("GPSPACE_COOKIE", raising=False)
    monkeypatch.delenv("GPSPACE_CONTENT_TYPE", raising=False)
    monkeypatch.setattr("gps_emi.cli.load_dotenv", lambda **kwargs: None)
