import signal
from threading import Event
from unittest.mock import Mock

import pytest

from gps_emi.whatsapp import server
from gps_emi.whatsapp.shutdown import Shutdown, ShutdownRequested
from gps_emi.whatsapp.webhook import create_app
from gps_emi.whatsapp.worker import Inbox


def test_health_is_local_even_without_configuration():
    class Forbidden:
        def __getattr__(self, name):
            pytest.fail('Health accessed configuration or inbox')
    client = create_app(Forbidden(), Forbidden()).test_client()
    for _ in range(3):
        response = client.get('/health')
        assert response.status_code == 200
        assert response.content_type == 'application/json'
        assert response.json == {'status': 'ok'}


@pytest.mark.parametrize('number,code', [(signal.SIGTERM, 0), (signal.SIGINT, 130)])
def test_entrypoint_signals_binding_and_restore(monkeypatch, wa_config, number, code):
    handlers = {}
    old = object()
    def register(sig, handler):
        handlers[sig] = handler
        return old
    monkeypatch.setattr(signal, 'signal', register)
    monkeypatch.setattr(server.WhatsAppConfig, 'from_env', lambda: wa_config)
    runtime, inbox, watches = Mock(), Mock(), Mock()
    runtime.run.side_effect = lambda: handlers[number](number, None)
    factory = Mock(return_value=runtime)
    monkeypatch.setattr(server, 'create_server', factory)
    monkeypatch.setattr(server, 'Inbox', Mock(return_value=inbox))
    monkeypatch.setattr(server, 'WatchManager', Mock(return_value=watches))
    assert server.main(['--host','0.0.0.0','--port','8123']) == code
    assert factory.call_args.kwargs['host'] == '0.0.0.0'
    assert factory.call_args.kwargs['port'] == 8123
    assert handlers == {signal.SIGINT: old, signal.SIGTERM: old}
    inbox.request_stop.assert_called_once()
    watches.request_stop.assert_called_once()
    runtime.close.assert_called_once()
    runtime.task_dispatcher.shutdown.assert_called_once()
    guarded_source = server.WatchManager.call_args.args[0]
    with pytest.raises(RuntimeError, match='cerrando'):
        guarded_source()


def test_shutdown_signals_all_before_wait_and_survives_failure(monkeypatch):
    from gps_emi.whatsapp import shutdown as module
    events = []
    clock = [0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    class Worker:
        def request_stop(self): events.append('stop')
        def close(self, timeout):
            events.append(('join', timeout))
            clock[0] += timeout
            return False
    runtime = Mock()
    runtime.close.side_effect = RuntimeError('internal')
    runtime.task_dispatcher.shutdown.side_effect = lambda timeout: events.append('http-stop')
    Shutdown().close(Worker(), Worker(), runtime, timeout=2)
    assert events == ['stop', 'stop', 'http-stop', ('join', 2), ('join', 0)]


def test_repeat_signal_does_not_interrupt_cleanup():
    shutdown = Shutdown()
    with pytest.raises(ShutdownRequested): shutdown.handle(signal.SIGTERM, None)
    shutdown.handle(signal.SIGINT, None)
    assert shutdown.signum == signal.SIGTERM


@pytest.mark.parametrize('operation,method', [('read','handle_read_event'), ('write','handle_write_event')])
def test_signal_escapes_real_waitress_socket_callback(operation, method):
    from waitress import wasyncore
    shutdown = Shutdown()
    channel = Mock()
    getattr(channel, method).side_effect = lambda: shutdown.handle(signal.SIGTERM, None)
    with pytest.raises(ShutdownRequested):
        getattr(wasyncore, operation)(channel)
    channel.handle_error.assert_not_called()


def test_inbox_stop_discards_queue_and_bounds_inflight():
    from gps_emi.whatsapp.webhook import IncomingMessage
    entered, release = Event(), Event()
    calls = []
    def handle(message):
        calls.append(message.message_id)
        entered.set()
        assert release.wait(2)
    inbox = Inbox(handle)
    inbox.submit([IncomingMessage('1','test','MENU',1),IncomingMessage('2','test','MENU',1)])
    inbox.start()
    try:
        assert entered.wait(1)
        inbox.request_stop()
        assert not inbox.submit([IncomingMessage('3','test','MENU',1)])
        assert inbox.close(timeout=0) is False
    finally:
        release.set()
        assert inbox.close(timeout=1)
    assert calls == ['1']


def test_multisocket_shutdown_closes_map_without_default_timeout(monkeypatch):
    from waitress import wasyncore
    close_all = Mock()
    monkeypatch.setattr(wasyncore,'close_all',close_all)
    class Runtime:
        map = {}
        task_dispatcher = Mock()
        def close(self): pytest.fail('Unbounded wrapper close used')
    runtime = Runtime()
    Shutdown().close(None,None,runtime,timeout=1)
    close_all.assert_called_once_with(runtime.map)
    assert 0 <= runtime.task_dispatcher.shutdown.call_args.kwargs['timeout'] <= 1
