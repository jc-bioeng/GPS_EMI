from unittest.mock import Mock

import pytest

from gps_emi.whatsapp import server


def test_server_missing_configuration_no_socket(monkeypatch):
    create = Mock()
    monkeypatch.setattr(server, 'create_server', create)
    assert server.main([]) == 1
    create.assert_not_called()


def test_server_wiring_and_shutdown(wa_config, monkeypatch):
    load, runtime, inbox, watches = Mock(), Mock(), Mock(), Mock()
    runtime.run.side_effect = KeyboardInterrupt()
    monkeypatch.setattr(server, 'load_dotenv', load)
    monkeypatch.setattr(server.WhatsAppConfig, 'from_env', lambda: wa_config)
    monkeypatch.setattr(server, 'create_server', Mock(return_value=runtime))
    monkeypatch.setattr(server, 'Inbox', Mock(return_value=inbox))
    monkeypatch.setattr(server, 'WatchManager', Mock(return_value=watches))
    assert server.main(['--port', '8001']) == 130
    load.assert_called_once_with(dotenv_path='.env', override=False)
    inbox.start.assert_called_once()
    inbox.close.assert_called_once()
    watches.close.assert_called_once()
    assert 0 <= inbox.close.call_args.kwargs['timeout'] <= 6
    assert 0 <= watches.close.call_args.kwargs['timeout'] <= 6
    runtime.close.assert_called_once()
    assert server.create_server.call_args.kwargs['host'] == '127.0.0.1'
    assert server.create_server.call_args.kwargs['port'] == 8001


def test_invalid_watch_config_never_loads_env(monkeypatch):
    load = Mock()
    monkeypatch.setattr(server, 'load_dotenv', load)
    assert server.main(['--interval', '0']) == 1
    load.assert_not_called()
