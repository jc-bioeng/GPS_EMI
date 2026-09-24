from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from gps_emi.models import Vehicle
from gps_emi.monitoring.watches import WatchStatus
from gps_emi.sites import EMI_SITES
from gps_emi.whatsapp.service import MessageService, WatchManager
from gps_emi.whatsapp.webhook import IncomingMessage, extract_messages, create_app
from gps_emi.whatsapp.worker import Inbox
from gps_emi.whatsapp.menu import cancel_menu_payload, menu_payload
from gps_emi.whatsapp.client import WhatsAppClient, WhatsAppError
from test_webhook import post
from test_interactive_ux import interactive_payload
from test_transport import response

NUMBER = '15555550101'
BASE = datetime(2026,9,22,12)


@pytest.fixture
def runtime(wa_config, messenger):
    source = Mock()
    source.get_vehicles.return_value = [Vehicle('1','PJU886',BASE,mobile_number='AMB-20'),
                                         Vehicle('2','QTQ899',BASE,mobile_number='AMB-18')]
    watches = WatchManager(lambda: source,messenger,wa_config,autostart=False)
    service = MessageService(wa_config,messenger,watches,lambda:source)
    return service,watches,source,messenger


def send(service,text,sender=NUMBER):
    service.handle(IncomingMessage('synthetic',sender,text,1000000))


def tap(service,config,selection):
    message, = extract_messages(interactive_payload(config,'list_reply',selection),config.phone_number_id)
    service.handle(message)


def test_new_watches_feedback_one_snapshot_and_duplicate(runtime,wa_config):
    service,watches,source,messenger = runtime
    tap(service,wa_config,'new_watch')
    send(service,'amb20')
    assert messenger.client.send_text.call_args.args[1] == '🔎 Buscando amb20...'
    source.get_vehicles.assert_not_called()
    send(service,'VIGILAR AMB-18')
    send(service,'VIGILAR PJU886')
    watches.polling.cycle()
    source.get_vehicles.assert_called_once()
    assert len(watches.list_active(NUMBER)) == 2
    texts = [call.args[1] for call in messenger.client.send_text.call_args_list]
    assert sum('Vigilancia iniciada' in text for text in texts) == 2
    assert 'ya tiene una vigilancia activa' in texts[-1]


@pytest.mark.parametrize('sites', [EMI_SITES[:1], EMI_SITES[1:], EMI_SITES])
def test_initial_inside_confirmation_keeps_watch_active(runtime, sites):
    service, watches, source, messenger = runtime
    initial = replace(source.get_vehicles.return_value[0], zones=list(sites))
    source.get_vehicles.return_value = [initial]
    send(service, 'VIGILAR AMB-20')
    watches.polling.cycle()
    text = messenger.client.send_text.call_args.args[1]
    assert 'La última posición reportada de AMB-20 · PJU886 corresponde a' in text
    assert 'próxima llegada después de observar una salida' in text
    assert 'Te avisaré cuando llegue' not in text
    if len(sites) == 2:
        assert 'sin sede única' in text
    else:
        assert ('Poblado' if sites == EMI_SITES[:1] else 'Taller') in text
    assert len(watches.list_active(NUMBER)) == 1
    recipient, choices = messenger.client.send_cancel_menu.call_args.args
    assert recipient == NUMBER and len(choices) == 1
    assert choices[0].watch_id == watches.list_active(NUMBER)[0].watch_id
    source.get_vehicles.assert_called_once()
    messenger.client.send_template.assert_not_called()
    count = messenger.client.send_text.call_count
    watches.polling.cycle()
    assert messenger.client.send_text.call_count == count
    source.get_vehicles.return_value = [replace(initial, zones=[], gps_timestamp=BASE+timedelta(seconds=30))]
    watches.polling.cycle()
    source.get_vehicles.return_value = [replace(initial, zones=[EMI_SITES[0]], gps_timestamp=BASE+timedelta(seconds=60))]
    watches.polling.cycle()
    messenger.client.send_template.assert_called_once()
    assert not watches.list_active(NUMBER)


@pytest.mark.parametrize('timestamp, zones', [(BASE, []), (None, [EMI_SITES[0]])])
def test_initial_outside_or_unprocessed_report_keeps_original_confirmation(runtime, timestamp, zones):
    service, watches, source, messenger = runtime
    source.get_vehicles.return_value = [replace(source.get_vehicles.return_value[0], zones=zones, gps_timestamp=timestamp)]
    send(service, 'VIGILAR AMB-20')
    watches.polling.cycle()
    text = messenger.client.send_text.call_args.args[1]
    assert 'Te avisaré cuando llegue a una sede EMI.' in text
    assert 'corresponde a' not in text
    messenger.client.send_cancel_menu.assert_not_called()


def test_initial_inside_cancel_option_only_stops_selected_watch(runtime, wa_config):
    service, watches, source, messenger = runtime
    source.get_vehicles.return_value = [replace(v, zones=[EMI_SITES[0]]) for v in source.get_vehicles.return_value]
    send(service, 'VIGILAR AMB-20')
    send(service, 'VIGILAR AMB-18')
    watches.polling.cycle()
    first_choice = messenger.client.send_cancel_menu.call_args_list[0].args[1][0]
    tap(service, wa_config, 'cancel_watch:' + first_choice.watch_id)
    assert watches.manager.get_watch(NUMBER, first_choice.watch_id).status == WatchStatus.CANCELLED
    assert len(watches.list_active(NUMBER)) == 1
    assert watches.list_active(NUMBER)[0].vehicle_id == '2'
    assert 'Vigilancia detenida' in messenger.client.send_text.call_args.args[1]
    messenger.client.send_template.assert_not_called()


def test_initial_inside_cancel_option_failure_keeps_watch(runtime):
    service, watches, source, messenger = runtime
    messenger.client.send_cancel_menu.side_effect = WhatsAppError('timeout')
    source.get_vehicles.return_value = [replace(source.get_vehicles.return_value[0], zones=[EMI_SITES[1]])]
    send(service, 'VIGILAR AMB-20')
    watches.polling.cycle()
    assert len(watches.list_active(NUMBER)) == 1
    assert 'escribir DETENER' in messenger.client.send_text.call_args.args[1]


def test_initial_inside_accepts_numeric_cancellation(runtime):
    service, watches, source, messenger = runtime
    source.get_vehicles.return_value = [replace(source.get_vehicles.return_value[0], zones=[EMI_SITES[0]])]
    send(service, 'VIGILAR AMB-20')
    watches.polling.cycle()
    send(service, '1')
    assert not watches.list_active(NUMBER)
    assert 'Vigilancia detenida' in messenger.client.send_text.call_args.args[1]


def test_list_cancel_native_and_keep_other(runtime,wa_config):
    service,watches,_,messenger = runtime
    send(service,'VIGILAR AMB-20');send(service,'VIGILAR AMB-18')
    watches.polling.cycle()
    tap(service,wa_config,'manage_watches')
    messenger.client.send_watch_menu.assert_called_once_with(NUMBER)
    tap(service,wa_config,'my_watches')
    text = messenger.client.send_text.call_args.args[1]
    assert 'AMB-20 · PJU886' in text and 'AMB-18 · QTQ899' in text
    assert not any(internal in text for internal in ('VEHID','OUTSIDE_EMI','INSIDE_EMI'))
    tap(service,wa_config,'stop_watch')
    _, choices = messenger.client.send_cancel_menu.call_args.args
    tap(service,wa_config,'cancel_watch:' + choices[1].watch_id)
    assert len(watches.list_active(NUMBER)) == 1
    assert watches.list_active(NUMBER)[0].vehicle_id == '1'
    assert 'Vigilancia detenida' in messenger.client.send_text.call_args.args[1]
    tap(service,wa_config,'cancel_watch:' + choices[1].watch_id)
    assert 'no está activa' in messenger.client.send_text.call_args.args[1]
    assert len(watches.list_active(NUMBER)) == 1


def test_empty_lists_and_cancel_owner_checks(runtime,wa_config):
    service,watches,_,messenger = runtime
    own,_ = watches.manager.create_watch('different-owner',Vehicle('1','P',mobile_number='AMB-20'),'other-target')
    send(service,'MISVIGILANCIAS')
    assert 'No tienes vigilancias activas' in messenger.client.send_text.call_args.args[1]
    tap(service,wa_config,'cancel_watch:' + own.watch_id)
    assert watches.manager.get_watch('different-owner',own.watch_id).status == WatchStatus.ACTIVE
    assert own.mobile_number not in messenger.client.send_text.call_args.args[1]
    send(service,'DETENER')
    assert 'No tienes vigilancias activas' in messenger.client.send_text.call_args.args[1]


def test_numeric_cancel_selection_stable_after_completion(runtime):
    service,watches,source,messenger = runtime
    send(service,'VIGILAR AMB-20');send(service,'VIGILAR AMB-18')
    watches.polling.cycle()
    send(service,'DETENER')
    choices = watches.list_active(NUMBER)
    watches.manager.cancel_watch(NUMBER,choices[0].watch_id)
    send(service,'1')
    assert 'ya no está activa' in messenger.client.send_text.call_args.args[1]
    assert watches.list_active(NUMBER)[0].watch_id == choices[1].watch_id
    send(service,'DETENER');send(service,'0');send(service,'1')
    assert not watches.list_active(NUMBER)


def test_notification_failed_is_completed_and_not_retried(runtime):
    service,watches,source,messenger = runtime
    messenger.client.send_template.side_effect = WhatsAppError('timeout')
    send(service,'VIGILAR AMB-20');send(service,'VIGILAR AMB-18')
    watches.polling.cycle()
    source.get_vehicles.return_value = [replace(v,gps_timestamp=BASE+timedelta(seconds=30), zones=[EMI_SITES[0]] if v.vehid=='1' else []) for v in source.get_vehicles.return_value]
    watches.polling.cycle();watches.polling.cycle()
    messenger.client.send_template.assert_called_once()
    assert messenger.client.send_template.call_args.args[0] == NUMBER
    first,second = watches.manager.list_watches(NUMBER)
    assert first.status == WatchStatus.COMPLETED and first.notification_status == 'failed'
    assert second.status == WatchStatus.ACTIVE


def test_cancellation_payload_and_window(wa_config,messenger):
    watches = WatchManager(Mock(),messenger,wa_config,autostart=False)
    watch,_ = watches.manager.create_watch(NUMBER,Vehicle('1','PLATE',mobile_number='MOVIL- 96'),NUMBER)
    transport = Mock(return_value=response())
    messenger.client = WhatsAppClient(wa_config,post=transport)
    with pytest.raises(WhatsAppError):
        messenger.cancel_menu(NUMBER,[watch])
    transport.assert_not_called()
    messenger.windows.note(NUMBER,1000000)
    messenger.cancel_menu(NUMBER,[watch])
    payload = transport.call_args.kwargs['json']
    assert payload['type'] == 'text'
    assert '1. MOVIL- 96 · PLATE' in payload['text']['body']
    assert [r['id'] for r in menu_payload(watches=True)['action']['sections'][0]['rows']] == ['new_watch','my_watches','stop_watch','main_menu']


def test_many_watches_use_numeric_selection_without_truncation(runtime):
    service,watches,_,messenger = runtime
    for i in range(11):
        watches.manager.create_watch(NUMBER,Vehicle(str(i),'P'+str(i),mobile_number='AMB-'+str(i)),NUMBER)
    send(service,'DETENER')
    messenger.client.send_cancel_menu.assert_not_called()
    assert '11. AMB-10' in messenger.client.send_text.call_args.args[1]
    send(service,'11')
    assert len(watches.list_active(NUMBER)) == 10


def test_signed_interactive_creation_dedup_and_denied(runtime,wa_config):
    service,watches,source,messenger = runtime
    inbox = Inbox(service.handle,now=lambda:0)
    client = create_app(wa_config,inbox).test_client()
    data = interactive_payload(wa_config,'list_reply','new_watch')
    assert post(client,wa_config,data,'sha256=wrong').status_code == 403
    assert not inbox.process_one()
    assert post(client,wa_config,data).status_code == 200
    assert post(client,wa_config,data).status_code == 200
    source.get_vehicles.assert_not_called()
    assert inbox.process_one() and not inbox.process_one()
    messenger.client.send_text.assert_called_once()
    denied = interactive_payload(wa_config,'list_reply','my_watches',sender='15555550102')
    denied['entry'][0]['changes'][0]['value']['messages'][0]['id'] = 'different'
    assert post(client,wa_config,denied).status_code == 200
    assert inbox.process_one()
    assert 'no está autorizado' in messenger.client.send_text.call_args.args[1]
    source.get_vehicles.assert_not_called()
