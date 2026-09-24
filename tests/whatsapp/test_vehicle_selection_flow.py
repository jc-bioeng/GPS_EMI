from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock

import pytest

from gps_emi.selection import PendingSelections, SelectionOperation
from gps_emi.whatsapp.service import MessageService, WatchManager
from gps_emi.whatsapp.vehicle_selection import selection_payload
from gps_emi.whatsapp.webhook import IncomingMessage, extract_messages, create_app
from gps_emi.whatsapp.worker import Inbox
from gps_emi.sites import EMI_SITES
from test_selection_protocol import candidates, offer
from test_interactive_ux import interactive_payload
from test_webhook import post
from gps_emi.whatsapp.client import WhatsAppClient, WhatsAppError
from test_transport import response

NUMBER = '15555550101'


@pytest.fixture
def runtime(wa_config,messenger):
    source = Mock()
    source.get_vehicles.return_value = list(candidates())
    watches = WatchManager(lambda:source,messenger,wa_config,autostart=False)
    service = MessageService(wa_config,messenger,watches,lambda:source)
    return service,watches,source,messenger


def send(service,text,sender=NUMBER):
    service.handle(IncomingMessage('id',sender,text,1000000))


def test_numeric_selection_refreshes_vehicle_and_rejects_invalid_number(runtime):
    service, _, source, messenger = runtime
    send(service, 'UBICACION PRU332')
    ctx = context(messenger)
    before = source.get_vehicles.call_count
    send(service, '99')
    assert source.get_vehicles.call_count == before
    assert 'número de la lista' in messenger.client.send_text.call_args.args[1]
    send(service, '2')
    assert source.get_vehicles.call_count == before + 1
    assert ctx.candidates[1].mobile_number in messenger.client.send_text.call_args.args[1]
    assert NUMBER not in service.vehicle_choices


def test_numeric_selection_menu_invalidates_choices(runtime):
    service, _, source, messenger = runtime
    send(service, 'UBICACION PRU332')
    send(service, 'MENU')
    before = source.get_vehicles.call_count
    send(service, '2')
    assert source.get_vehicles.call_count == before
    assert 'Escribe la placa' in messenger.client.send_text.call_args.args[1]


def test_numeric_selection_pagination_and_expiration(runtime):
    service, _, source, messenger = runtime
    source.get_vehicles.return_value = [replace(candidates()[0], vehid=str(i), mobile_number=f'AMB-{i}') for i in range(12)]
    send(service, 'UBICACION PRU332')
    ctx = context(messenger)
    send(service, '9')  # Ocho candidatos y Siguiente.
    assert messenger.client.send_vehicle_selection.call_args.args[3] == 1
    assert service.vehicle_choices[NUMBER][0].endswith(ctx.choice_ids[8])
    service.selections.now = lambda: ctx.created_at + 301
    before = source.get_vehicles.call_count
    send(service, '1')
    assert source.get_vehicles.call_count == before
    assert 'expiró' in messenger.client.send_text.call_args.args[1]


def context(messenger):
    return messenger.client.send_vehicle_selection.call_args.args[1]


def choose(service,wa_config,ctx,index=1,sender=NUMBER):
    selection = 'vehicle_select:'+ctx.selection_id+':'+ctx.choice_ids[index]
    incoming, = extract_messages(interactive_payload(wa_config,'list_reply',selection,sender),wa_config.phone_number_id)
    service.handle(incoming)


def test_selector_contains_all_candidates_no_unnecessary_id():
    ctx = offer(PendingSelections())
    body = selection_payload(ctx)
    rows = body['action']['sections'][0]['rows']
    assert len(rows) == 3
    assert [row['title'] for row in rows] == [v.mobile_number for v in candidates()]
    assert all('PRU332' in row['description'] and 'Ubicación' in row['description'] for row in rows)
    assert 'VEHID' not in str(body) and 'Registro:' not in str(body)
    assert len({row['id'] for row in rows}) == 3


def test_pagination_and_meta_lengths_preserve_candidates():
    store = PendingSelections()
    rows = tuple(replace(candidates()[0],vehid=str(i),mobile_number='Móvil largo '+str(i)*30) for i in range(21))
    ctx = store.offer('A',SelectionOperation.LOCATION,'X',rows,'target',store.begin('A'))
    offered = []
    for page in range(3):
        payload = selection_payload(ctx,page=page)
        items = payload['action']['sections'][0]['rows']
        assert len(items) <= 10 and len(payload['body']['text']) <= 1024
        for item in items:
            assert len(item['id']) <= 200 and 0 < len(item['title']) <= 24
            assert len(item.get('description','')) <= 72
            if item['id'].startswith('vehicle_select:'):
                offered.append(item['id'])
    assert len(offered) == len(set(offered)) == 21


def test_identical_visible_data_uses_available_diagnostics_then_id():
    store = PendingSelections()
    a = candidates()[0]
    b = replace(a,vehid='distinct',gps_fix=9)
    ctx = store.offer('A',SelectionOperation.LOCATION,'PRU332',(a,b),'t',store.begin('A'))
    rows = selection_payload(ctx)['action']['sections'][0]['rows']
    assert 'Fix:' in rows[0]['description'] and rows[0]['description'] != rows[1]['description']
    b = replace(a,vehid='distinct')
    ctx = store.offer('A',SelectionOperation.LOCATION,'PRU332',(a,b),'t',store.begin('A'))
    rows = selection_payload(ctx)['action']['sections'][0]['rows']
    assert rows[0]['description'].startswith('Registro:') and rows[0]['description'] != rows[1]['description']


def test_location_selects_second_refreshes_exact_id_and_consumes(runtime,wa_config):
    service,watches,source,messenger = runtime
    send(service,'UBICACION PRU332')
    ctx = context(messenger)
    assert ctx.operation == SelectionOperation.LOCATION
    assert not watches.list_active(NUMBER)
    selected = replace(candidates()[1],plate='CHANGED',mobile_number='RENAMED',location='Solo segundo')
    source.get_vehicles.return_value = [candidates()[2],selected,candidates()[0]]
    choose(service,wa_config,ctx)
    text = messenger.client.send_text.call_args.args[1]
    assert 'Solo segundo' in text and 'RENAMED' in text and 'CHANGED' in text
    assert 'Ubicación 1' not in text and 'Ubicación 3' not in text
    assert source.get_vehicles.call_count == 2
    choose(service,wa_config,ctx)
    assert source.get_vehicles.call_count == 2


def test_watch_selection_vehid_duplicate_and_later_arrival(runtime,wa_config):
    service,watches,source,messenger = runtime
    send(service,'VIGILAR PRU332')
    source.get_vehicles.assert_not_called()
    watches.polling.cycle()
    assert not watches.list_active(NUMBER)
    ctx = context(messenger)
    assert ctx.operation == SelectionOperation.CREATE_WATCH
    choose(service,wa_config,ctx)
    assert source.get_vehicles.call_count == 1
    watches.polling.cycle()
    watch, = watches.list_active(NUMBER)
    assert watch.vehicle_id == '2' and watch.owner_id == NUMBER and watch.notification_target == NUMBER
    send(service,'VIGILAR PRU332');watches.polling.cycle()
    choose(service,wa_config,context(messenger));watches.polling.cycle()
    assert len(watches.list_active(NUMBER)) == 1
    assert 'ya tiene una vigilancia activa' in messenger.client.send_text.call_args.args[1]
    source.get_vehicles.return_value = [replace(v, gps_timestamp=v.gps_timestamp+timedelta(seconds=30),
        zones=list(EMI_SITES[:1]) if v.vehid=='2' else [], mobile_number='RENAMED' if v.vehid=='2' else v.mobile_number) for v in candidates()]
    watches.polling.cycle()
    messenger.client.send_template.assert_called_once()
    assert messenger.client.send_template.call_args.args[-1][0] == 'RENAMED'
    assert not watches.list_active(NUMBER)


@pytest.mark.parametrize('operation', ['UBICACION','VIGILAR'])
@pytest.mark.parametrize('missing', [True,False])
def test_changed_snapshot_no_fallback(runtime,wa_config,operation,missing):
    service,watches,source,messenger = runtime
    send(service,operation+' PRU332')
    if operation == 'VIGILAR':
        watches.polling.cycle()
    ctx = context(messenger)
    source.get_vehicles.return_value = [candidates()[0],candidates()[2]] if missing else [candidates()[1],candidates()[1]]
    choose(service,wa_config,ctx)
    if operation == 'VIGILAR':
        watches.polling.cycle()
    assert 'ya no está disponible' in messenger.client.send_text.call_args.args[1]
    assert not watches.list_active(NUMBER)
    count = source.get_vehicles.call_count
    choose(service,wa_config,ctx)
    assert source.get_vehicles.call_count == count


@pytest.mark.parametrize('reset', ['MENU','MENÚ','INICIO','CANCELAR','UBICACION PRU332 DEMO'])
def test_reset_invalidates_old_selector(runtime,wa_config,reset):
    service,watches,source,messenger = runtime
    send(service,'UBICACION PRU332')
    ctx = context(messenger)
    send(service,reset)
    count = source.get_vehicles.call_count
    choose(service,wa_config,ctx)
    assert source.get_vehicles.call_count == count
    assert 'selección no es válida' in messenger.client.send_text.call_args.args[1]


def test_late_watch_selector_after_menu_is_ignored(runtime):
    service,watches,_,messenger = runtime
    send(service,'VIGILAR PRU332')
    send(service,'MENU')
    watches.polling.cycle()
    messenger.client.send_vehicle_selection.assert_not_called()


def test_expiry_and_owner_security(runtime,wa_config):
    service,_,source,messenger = runtime
    clock = [0]
    service.selections.now = lambda:clock[0]
    send(service,'UBICACION PRU332')
    ctx = context(messenger)
    # Otro propietario autorizado tampoco puede consumirlo.
    service.config = replace(wa_config,allowed_numbers=frozenset({NUMBER,'15555550102'}))
    choose(service,wa_config,ctx,sender='15555550102')
    assert source.get_vehicles.call_count == 1
    clock[0] = 300
    choose(service,wa_config,ctx)
    assert 'expiró' in messenger.client.send_text.call_args.args[1]
    assert source.get_vehicles.call_count == 1


def test_signed_selection_webhook_nonblocking_dedup_allowlist(runtime,wa_config):
    service,_,source,messenger = runtime
    send(service,'UBICACION PRU332');ctx = context(messenger)
    selection = 'vehicle_select:'+ctx.selection_id+':'+ctx.choice_ids[1]
    data = interactive_payload(wa_config,'list_reply',selection)
    inbox = Inbox(service.handle,now=lambda:0)
    client = create_app(wa_config,inbox).test_client()
    assert post(client,wa_config,data,'sha256=bad').status_code == 403
    assert not inbox.process_one()
    assert post(client,wa_config,data).status_code == 200
    assert post(client,wa_config,data).status_code == 200
    assert source.get_vehicles.call_count == 1
    assert inbox.process_one() and not inbox.process_one()
    assert source.get_vehicles.call_count == 2
    denied = interactive_payload(wa_config,'list_reply',selection,'15555550102')
    denied['entry'][0]['changes'][0]['value']['messages'][0]['id'] = 'denied'
    post(client,wa_config,denied);inbox.process_one()
    assert source.get_vehicles.call_count == 2
    assert 'no está autorizado' in messenger.client.send_text.call_args.args[1]


def test_transport_contract_service_window_and_pagination(wa_config,messenger):
    transport = Mock(return_value=response())
    messenger.client = WhatsAppClient(wa_config,post=transport)
    ctx = offer(PendingSelections())
    with pytest.raises(WhatsAppError,match='service_window_closed'):
        messenger.vehicle_selection(NUMBER,ctx)
    transport.assert_not_called()
    messenger.windows.note(NUMBER,1000000)
    messenger.vehicle_selection(NUMBER,ctx)
    payload = transport.call_args.kwargs['json']
    assert payload['to'] == NUMBER and payload['messaging_product'] == 'whatsapp'
    assert payload['type'] == 'text'
    assert '1. ' in payload['text']['body']
    assert '_Responde con el número' in payload['text']['body']


def test_unoffered_choice_rejected_then_valid_choice_works(runtime,wa_config):
    service,_,source,messenger = runtime
    send(service,'UBICACION PRU332');ctx = context(messenger)
    send(service,'VEHICLE_SELECT '+ctx.selection_id+':'+'0'*32)
    assert source.get_vehicles.call_count == 1
    choose(service,wa_config,ctx)
    assert source.get_vehicles.call_count == 2


def test_pagination_preserves_operation_and_does_not_consume(runtime,wa_config):
    service,_,source,messenger = runtime
    source.get_vehicles.return_value = [replace(candidates()[0],vehid=str(i),mobile_number='Nombre '+str(i)) for i in range(12)]
    send(service,'UBICACION PRU332');ctx = context(messenger)
    incoming, = extract_messages(interactive_payload(wa_config,'list_reply','vehicle_page:'+ctx.selection_id+':1'),wa_config.phone_number_id)
    service.handle(incoming)
    assert messenger.client.send_vehicle_selection.call_args.args[-1] == 1
    assert source.get_vehicles.call_count == 1
    choose(service,wa_config,ctx,index=10)
    assert 'Nombre 10' in messenger.client.send_text.call_args.args[1]
    assert source.get_vehicles.call_count == 2


def test_ambiguous_watch_selection_shares_cycle_with_other_watches(runtime,wa_config):
    service,watches,source,messenger = runtime
    send(service,'VIGILAR PRU332 DEMO')
    send(service,'VIGILAR PRU332')
    watches.polling.cycle()
    assert source.get_vehicles.call_count == 1
    assert len(watches.list_active(NUMBER)) == 1
    choose(service,wa_config,context(messenger))
    watches.polling.cycle()
    assert source.get_vehicles.call_count == 2 and len(watches.list_active(NUMBER)) == 2
