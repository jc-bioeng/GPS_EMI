import os
import uuid
from unittest.mock import Mock

import pytest

from gps_emi.whatsapp.config import WhatsAppConfig
from gps_emi.whatsapp.delivery import Messenger, ServiceWindow


@pytest.fixture(autouse=True)
def isolated_whatsapp(monkeypatch):
    for name in list(os.environ):
        if name.startswith('WHATSAPP_'):
            monkeypatch.delenv(name)
    monkeypatch.setattr('gps_emi.whatsapp.server.load_dotenv', lambda **kwargs: None)
    monkeypatch.setattr('gps_emi.whatsapp.server.configure_logging', lambda level: None)


@pytest.fixture
def wa_config():
    # Credenciales efímeras sintéticas, nunca tomadas del entorno real.
    return WhatsAppConfig(uuid.uuid4().hex, '123456789', uuid.uuid4().hex,
                          uuid.uuid4().hex, frozenset({'15555550101'}))


@pytest.fixture
def messenger():
    return Messenger(Mock(), ServiceWindow(now=lambda: 1000000))
