"""Aliases use the existing state machine and preserve selection/owner controls."""
import pytest

from gps_emi.whatsapp.routing import parse_command, Conversation, State, COMMAND_ALIASES
from test_watch_management import runtime, send, NUMBER


@pytest.mark.parametrize('canonical,alias', [(canonical, alias) for canonical, aliases in COMMAND_ALIASES.items() for alias in aliases])
def test_alias_matches_canonical_command(canonical, alias):
    assert parse_command(alias) == parse_command(canonical)
    assert parse_command(alias.upper()) == parse_command(canonical)


@pytest.mark.parametrize('verb', ['vigila', 'vigilancia', 'iniciar vigilancia', 'ubica', 'ubicar', 'localizar', 'consultar ubicación'])
def test_alias_preserves_original_identifier(verb):
    parsed = parse_command('  '+verb+'   áMb-20  ')
    assert parsed.argument == 'áMb-20'
    assert parsed.action in ('location', 'watch')


@pytest.mark.parametrize('text,action', [
    ('MÍS   VIGILÁNCIAS', 'list_watches'), ('Mis\tVigilancias', 'list_watches'),
    ('Ubicacio\u0301n AMB-20', 'location'), ('MENÚ PRINCIPAL', 'menu'),
    ('detener vigilancias', 'prompt_cancel'), ('parar vigilancia', 'prompt_cancel'),
])
def test_accents_whitespace_and_case(text, action):
    assert parse_command(text).action == action


@pytest.mark.parametrize('text', ['ubicarme', 'vigilante', 'mis vigilancias ajenas', 'detener todas las vigilancias'])
def test_no_partial_command_or_implicit_bulk_cancel(text):
    command = parse_command(text)
    assert command is None or command.action == 'invalid'


def test_aliases_work_while_waiting_for_identifier():
    conversation = Conversation()
    conversation.route(NUMBER, 'vigila')
    assert conversation.states[NUMBER] == State.WAITING_WATCH_IDENTIFIER
    assert conversation.route(NUMBER, 'mis vigilancias').action == 'list_watches'
    conversation.route(NUMBER, 'ubicar')
    assert conversation.states[NUMBER] == State.WAITING_LOCATION_IDENTIFIER
    assert conversation.route(NUMBER, 'AMB-20').action == 'location'


def test_list_and_stop_aliases_keep_owner_selection(runtime):
    service, watches, _, messenger = runtime
    send(service, 'vigila AMB-20')
    send(service, 'vigilancia AMB-18')
    watches.polling.cycle()
    send(service, 'mis vigilancias')
    assert 'AMB-20' in messenger.client.send_text.call_args.args[1]
    assert 'AMB-18' in messenger.client.send_text.call_args.args[1]
    send(service, 'detener vigilancias')
    assert len(watches.list_active(NUMBER)) == 2
    send(service, '1')
    assert len(watches.list_active(NUMBER)) == 1
