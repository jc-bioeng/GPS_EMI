from dataclasses import replace
from threading import Event, Thread
from unittest.mock import Mock

from gps_emi.acquisition import AcquisitionConfig
from gps_emi.whatsapp.service import MessageService, WatchManager
from gps_emi.whatsapp.webhook import IncomingMessage, create_app
from gps_emi.whatsapp.worker import Inbox
from test_central_acquisition import rig, row


A, B = '15555550101', '15555550102'


def setup(wa_config, messenger, *responses, config=None):
    central, source, clock, transport = rig(*responses, config=config)
    wa_config = replace(wa_config, allowed_numbers=frozenset({A, B}))
    watches = WatchManager(lambda: source, messenger, wa_config, autostart=False)
    service = MessageService(wa_config, messenger, watches, lambda: source)
    inbox = Inbox(service.handle, on_idle=service.drain_pending)
    return central, clock, transport, watches, service, inbox


def send(inbox, text, sender=A, message_id='test'):
    assert inbox.submit([IncomingMessage(message_id, sender, text, 1000000)])
    assert inbox.process_one()


def test_first_snapshot_async_inbox_remains_available_and_owner_isolation(wa_config, messenger):
    central, clock, transport, watches, service, inbox = setup(wa_config, messenger, (row(),))
    send(inbox, 'UBICACION TEST1')
    assert len(service.pending_queries) == 1
    transport.acquire.assert_not_called()
    assert 'inicializando' in messenger.client.send_text.call_args.args[1]
    send(inbox, 'UBICACION TEST1', B, 'b-query')
    send(inbox, 'MENU', A, 'a-menu')
    messenger.client.send_menu.assert_called_once_with(A)
    assert A not in service.pending_queries and B in service.pending_queries
    central.tick(); service.drain_pending()
    assert not service.pending_queries
    final = messenger.client.send_text.call_args.args
    assert final[0] == B and 'TEST1' in final[1]
    transport.acquire.assert_called_once()


def test_replaced_query_ttl_capacity_and_no_late_response(wa_config, messenger):
    central, clock, transport, watches, service, inbox = setup(
        wa_config, messenger, (row(),), config=AcquisitionConfig(capacity=1, pending_timeout=5))
    send(inbox, 'UBICACION REPLACED')
    send(inbox, 'UBICACION TEST1', message_id='new')
    assert len(service.pending_queries) == 1
    send(inbox, 'UBICACION TEST1', B, 'capacity')
    assert B not in service.pending_queries
    clock.advance(5)
    central.tick(); service.drain_pending()
    assert not service.pending_queries
    transport.acquire.assert_not_called()
    assert 'no está disponible' in messenger.client.send_text.call_args.args[1]
    # Expiry leaves no orphan demand that can deliver a response later.
    central.demand('test', True); central.tick(); service.drain_pending()
    assert 'no está disponible' in messenger.client.send_text.call_args.args[1]


def test_http_wait_never_blocks_inbox_menu_or_cancellation(wa_config, messenger):
    entered, release = Event(), Event()
    central, clock, transport, watches, service, inbox = setup(wa_config, messenger)
    def acquire():
        entered.set()
        assert release.wait(3)
        return (row(),)
    transport.acquire.side_effect = acquire
    send(inbox, 'UBICACION TEST1')
    thread = Thread(target=central.tick)
    thread.start()
    try:
        assert entered.wait(3)
        send(inbox, 'MENU', message_id='menu')
        messenger.client.send_menu.assert_called_once()
        assert not service.pending_queries
    finally:
        release.set(); thread.join(3)
    service.drain_pending()
    assert not any('Hora GPS:' in c.args[1] for c in messenger.client.send_text.call_args_list)


def test_query_watch_and_campaign_use_one_official_publication(wa_config, messenger):
    from pathlib import Path
    from gps_emi.acquisition import LabelMapping, SnapshotSource
    from gps_emi.providers.widetech_official import parse_render_excel
    result = parse_render_excel((Path(__file__).parents[1]/'fixtures'/'render_excel.xml').read_bytes())
    result = replace(result, diagnostics=(), duplicate_ids=(), incomplete_rows=())
    central, base_source, clock, transport = rig(result)
    source = SnapshotSource(central, LabelMapping('VEH_NAM', 'Movil'))
    # Do not infer label format from a fixture: use the explicitly configured projection.
    central.request(); central.tick()
    vehicle = source.get_vehicles()[0]
    collector = Mock(active=True)
    watches = WatchManager(lambda: source, messenger, wa_config, autostart=False, collector=collector)
    service = MessageService(wa_config, messenger, watches, lambda: source)
    inbox = Inbox(service.handle, on_idle=service.drain_pending)
    send(inbox, 'UBICACION '+vehicle.plate)
    send(inbox, 'VIGILAR '+vehicle.plate, message_id='watch')
    watches.polling.cycle()
    assert len(watches.list_active(A)) == 1
    transport.acquire.assert_called_once()
    collector.submit.assert_not_called()  # registration/cache is not a new acquisition
    transport.acquire.side_effect = [result]
    clock.advance(30); central.tick(); watches.polling.cycle()
    collector.submit.assert_called_once()
    assert transport.acquire.call_count == 2


def test_health_does_not_request_acquisition(wa_config, messenger):
    central, clock, transport, watches, service, inbox = setup(wa_config, messenger)
    app = create_app(wa_config, inbox)
    assert app.test_client().get('/health').status_code == 200
    central.tick()
    assert not central.pending
    transport.acquire.assert_not_called()
