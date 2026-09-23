from unittest.mock import Mock

import pytest

from gps_emi.models import Vehicle
from gps_emi.errors import SessionExpiredError, TransientAcquisitionError
from gps_emi.sites import EMI_SITES
from gps_emi.whatsapp.routing import parse_command, Conversation, State
from gps_emi.whatsapp.service import MessageService
from gps_emi.whatsapp.webhook import IncomingMessage
from gps_emi.whatsapp import formatting as fmt


@pytest.mark.parametrize('text,action,argument', [
    ('MENU', 'menu', ''), (' menú ', 'menu', ''), ('inicio', 'menu', ''), ('AYUDA', 'help', ''),
    ('VIGILAR AMB-20', 'watch', 'AMB-20'), ('vigilar amb-20', 'watch', 'amb-20'),
    ('VIGILAR   AMB-20', 'watch', 'AMB-20'), ('UBICACION AMB-20', 'location', 'AMB-20'),
    ('UBICACIÓN PJU886', 'location', 'PJU886'), ('UBICACION MOVIL- 96', 'location', 'MOVIL- 96'),
    ('SEDE POBLADO', 'site', EMI_SITES[0]), (' sede   taller ', 'site', EMI_SITES[1]),
    ('VIGILAR', 'prompt_watch', ''), ('UBICACIÓN', 'prompt_location', ''), ('SEDE', 'prompt_site', ''),
    ('MENU X', 'invalid', ''), ('SEDE otra', 'invalid', ''),
])
def test_parser(text, action, argument):
    command = parse_command(text)
    assert (command.action, command.argument) == (action, argument)


@pytest.mark.parametrize('text', ['', '   ', 'hola', 'DESCONOCIDO X'])
def test_unknown_parser(text):
    assert parse_command(text) is None


@pytest.mark.parametrize('choice,state,answer,action,arg', [
    ('1', State.WAITING_WATCH_IDENTIFIER, 'AMB-20', 'watch', 'AMB-20'),
    ('2', State.WAITING_LOCATION_IDENTIFIER, 'PJU886', 'location', 'PJU886'),
    ('3', State.WAITING_SITE, '1', 'site', EMI_SITES[0]),
    ('3', State.WAITING_SITE, '2', 'site', EMI_SITES[1]),
])
def test_menu_states(choice, state, answer, action, arg):
    conversation = Conversation()
    assert conversation.route('a', choice).action == 'reply'
    assert conversation.states['a'] == state
    assert conversation.route('b', 'MENU').argument == fmt.MENU
    result = conversation.route('a', answer)
    assert (result.action, result.argument) == (action, arg)
    assert 'a' not in conversation.states


def test_reset_override_help_and_invalid_site():
    c = Conversation()
    c.route('a', '1')
    assert c.route('a', 'MENU').argument == fmt.MENU
    assert not c.states
    c.route('a', '3')
    assert c.route('a', 'invalid').action == 'reply'
    assert c.states['a'] == State.WAITING_SITE
    assert c.route('a', 'UBICACION MOVIL- 96').argument == 'MOVIL- 96'
    assert not c.states
    assert c.route('a', '4').argument == fmt.HELP
    assert c.route('a', 'AYUDA').argument == fmt.HELP


@pytest.fixture
def service(wa_config, messenger):
    source = Mock()
    source.get_vehicles.return_value = [Vehicle('433909', 'PJU886', mobile_number='AMB-20',
                                              location='Dirección', zones=[EMI_SITES[0]])]
    return MessageService(wa_config, messenger, Mock(), Mock(return_value=source))


def deliver(service, text, sender='15555550101', timestamp=1000000):
    service.handle(IncomingMessage('id', sender, text, timestamp))


@pytest.mark.parametrize('command', ['UBICACION AMB-20', 'VIGILAR AMB-20', 'SEDE TALLER', 'MENU', '1'])
def test_unauthorized_never_consults_or_reveals(service, command):
    deliver(service, command, '15555550102')
    service.source_factory.assert_not_called()
    service.watches.start.assert_not_called()
    service.messenger.client.send_text.assert_called_once_with('15555550102', fmt.DENIED)
    assert not service.conversation.states and not service.messenger.windows.last_inbound


@pytest.mark.parametrize('steps', [['2', 'AMB-20'], ['UBICACION AMB-20'], ['UBICACIÓN PJU886']])
def test_menu_and_commands_share_real_i3_location(service, steps):
    for step in steps:
        deliver(service, step)
    service.source_factory.return_value.get_vehicles.assert_called_once()
    text = service.messenger.client.send_text.call_args.args[1]
    assert 'AMB-20' in text and 'PJU886' in text and 'Dirección' in text


@pytest.mark.parametrize('steps', [['3', '1'], ['SEDE POBLADO'], ['SEDE TALLER']])
def test_menu_and_commands_share_i3_inventory(service, steps):
    for step in steps:
        deliver(service, step)
    service.source_factory.return_value.get_vehicles.assert_called_once()
    assert 'última posición reportada' in service.messenger.client.send_text.call_args.args[1]


@pytest.mark.parametrize('steps,identifier', [(['1', 'AMB-20'], 'AMB-20'), (['VIGILAR AMB-20'], 'AMB-20'),
                                            (['VIGILAR PJU886'], 'PJU886')])
def test_menu_and_quick_watch_same_manager(service, steps, identifier):
    for step in steps:
        deliver(service, step)
    service.watches.start.assert_called_once_with('15555550101', identifier)
    service.source_factory.assert_not_called()


def test_closed_watch_service_no_new_gps(service):
    service.watches.start.return_value = False
    deliver(service, 'VIGILAR AMB-20')
    assert 'servicio de vigilancias está detenido' in service.messenger.client.send_text.call_args.args[1]
    service.source_factory.assert_not_called()


@pytest.mark.parametrize('rows,fragment', [([], 'No encontré'),
    ([Vehicle('1', 'X'), Vehicle('2', 'X')], 'ambiguo')])
def test_resolution_errors(service, rows, fragment):
    service.source_factory.return_value.get_vehicles.return_value = rows
    deliver(service, 'UBICACION X')
    if rows:
        context = service.messenger.client.send_vehicle_selection.call_args.args[1]
        assert context.candidates == tuple(rows)
    else:
        assert fragment in service.messenger.client.send_text.call_args.args[1]


@pytest.mark.parametrize('error', [SessionExpiredError, TransientAcquisitionError, RuntimeError])
def test_safe_errors(service, wa_config, error, caplog):
    service.source_factory.return_value.get_vehicles.side_effect = error(wa_config.access_token)
    deliver(service, 'UBICACION AMB-20')
    text = service.messenger.client.send_text.call_args.args[1]
    assert wa_config.access_token not in text + caplog.text
    assert 'Traceback' not in text + caplog.text


@pytest.mark.parametrize('sender,timestamp', [('username', 1000000), ('15555550101', 1),
                                          ('15555550101', 1000061)])
def test_invalid_sender_or_expired_message_no_gps(service, sender, timestamp):
    deliver(service, 'UBICACION AMB-20', sender, timestamp)
    service.source_factory.assert_not_called()
