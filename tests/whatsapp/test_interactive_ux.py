from unittest.mock import Mock

import pytest

from gps_emi.errors import SessionExpiredError
from gps_emi.models import Vehicle
from gps_emi.whatsapp.client import WhatsAppClient, WhatsAppError
from gps_emi.whatsapp.menu import COMMANDS
from gps_emi.whatsapp.routing import Conversation
from gps_emi.whatsapp.service import MessageService
from gps_emi.whatsapp.webhook import IncomingMessage, create_app, extract_messages
from gps_emi.whatsapp.worker import Inbox
from test_transport import response
from test_webhook import payload, post

NUMBER = '15555550101'


def test_numeric_watch_menu_has_context_and_returns_to_main_menu():
    conversation = Conversation()
    assert conversation.route(NUMBER, '5').action == 'watch_menu'
    assert conversation.route(NUMBER, '9').action == 'watch_menu'
    assert conversation.route(NUMBER, '2').action == 'list_watches'
    assert conversation.route(NUMBER, 'VIGILANCIAS').action == 'watch_menu'
    assert conversation.route(NUMBER, '3').action == 'prompt_cancel'
    conversation.route(NUMBER, 'VIGILANCIAS')
    assert conversation.route(NUMBER, '4').action == 'menu'
    assert 'Escribe la placa' in conversation.route(NUMBER, '2').argument


def interactive_payload(config, kind, selection, sender=NUMBER):
    data = payload(config, sender=sender)
    message = data['entry'][0]['changes'][0]['value']['messages'][0]
    message.pop('text')
    message.update(type='interactive', interactive={
        'type': kind, kind: {'id': selection, 'title': 'Texto visible ignorado'}})
    return data


def test_menu_serialization_and_window(wa_config, messenger):
    transport = Mock(return_value=response())
    messenger.client = WhatsAppClient(wa_config, post=transport)
    with pytest.raises(WhatsAppError, match='service_window_closed'):
        messenger.menu(NUMBER)
    transport.assert_not_called()
    messenger.windows.note(NUMBER, 1000000)
    messenger.menu(NUMBER)
    generated = transport.call_args.kwargs['json']
    assert generated['type'] == 'text'
    assert '5️⃣ Gestionar vigilancias' in generated['text']['body']
    assert '_Responde con el número' in generated['text']['body']
    assert 'interactive' not in generated



@pytest.mark.parametrize('kind', ['button_reply', 'list_reply'])
@pytest.mark.parametrize('selection,number', [('watch_arrival', '1'), ('vehicle_location', '2'),
                                             ('vehicles_at_site', '3'), ('help', '4')])
def test_interactive_uses_same_conversation(wa_config, kind, selection, number):
    message, = extract_messages(interactive_payload(wa_config, kind, selection), wa_config.phone_number_id)
    assert message.text == COMMANDS[selection]
    tapped, typed = Conversation(), Conversation()
    assert tapped.route(NUMBER, message.text) == typed.route(NUMBER, number)
    assert tapped.states == typed.states
    # Un menú anterior sigue siendo una acción, incluso durante otro prompt.
    tapped.route(NUMBER, 'SEDE')
    assert tapped.route(NUMBER, message.text) == Conversation().route(NUMBER, number)


@pytest.mark.parametrize('selection', ['unknown', '', None, [], {}])
def test_unknown_or_malformed_reply_is_ignored(wa_config, selection):
    assert not extract_messages(interactive_payload(wa_config, 'list_reply', selection), wa_config.phone_number_id)


@pytest.mark.parametrize('kind', ['button_reply', 'list_reply'])
def test_interactive_signature_allowlist_dedup(wa_config, messenger, kind):
    source, watches = Mock(), Mock()
    service = MessageService(wa_config, messenger, watches, source)
    inbox = Inbox(service.handle, now=lambda: 0)
    client = create_app(wa_config, inbox).test_client()
    data = interactive_payload(wa_config, kind, 'vehicle_location')
    assert post(client, wa_config, data, 'sha256=wrong').status_code == 403
    assert not inbox.process_one()
    assert post(client, wa_config, data).status_code == 200
    messenger.client.send_text.assert_not_called()
    assert post(client, wa_config, data).status_code == 200
    assert inbox.process_one() and not inbox.process_one()
    messenger.client.send_text.assert_called_once()
    denied = interactive_payload(wa_config, kind, 'watch_arrival', '15555550102')
    denied['entry'][0]['changes'][0]['value']['messages'][0]['id'] = 'denied'
    assert post(client, wa_config, denied).status_code == 200
    assert inbox.process_one()
    source.assert_not_called()
    watches.start.assert_not_called()
    assert '15555550102' not in service.conversation.states


@pytest.mark.parametrize('command', ['UBICACION amb20', 'SEDE POBLADO', 'SEDE TALLER'])
@pytest.mark.parametrize('fail', [False, True])
def test_feedback_precedes_acquisition_and_error(wa_config, messenger, command, fail):
    events = []
    messenger.client.send_text.side_effect = lambda recipient, text: events.append(text)
    source = Mock()
    def acquire():
        assert len(events) == 1 and events[0].startswith('🔎 Consultando ')
        events.append('ACQUIRE')
        if fail:
            raise SessionExpiredError()
        return [Vehicle('1', 'PJU886', mobile_number='AMB-20')]
    source.get_vehicles.side_effect = acquire
    service = MessageService(wa_config, messenger, Mock(), lambda: source)
    service.handle(IncomingMessage('id', NUMBER, command, 1000000))
    assert len(events) == 3
    assert 'No fue posible consultar' in events[-1] if fail else 'última posición reportada' in events[-1].lower()
    source.get_vehicles.assert_called_once()


def test_feedback_send_failure_does_not_cancel_query(wa_config, messenger):
    messenger.client.send_text.side_effect = [WhatsAppError('timeout'), None]
    source = Mock()
    source.get_vehicles.return_value = [Vehicle('1', 'PJU886', mobile_number='AMB-20')]
    service = MessageService(wa_config, messenger, Mock(), lambda: source)
    service.handle(IncomingMessage('id', NUMBER, 'UBICACION amb20', 1000000))
    source.get_vehicles.assert_called_once()
    assert messenger.client.send_text.call_count == 2
    assert 'PJU886' in messenger.client.send_text.call_args.args[1]


@pytest.mark.parametrize('text', ['MENU', 'MENÚ', 'INICIO'])
def test_menu_commands_send_native_menu(wa_config, messenger, text):
    source = Mock()
    service = MessageService(wa_config, messenger, Mock(), source)
    service.handle(IncomingMessage('id', NUMBER, text, 1000000))
    messenger.client.send_menu.assert_called_once_with(NUMBER)
    messenger.client.send_text.assert_not_called()
    source.assert_not_called()
