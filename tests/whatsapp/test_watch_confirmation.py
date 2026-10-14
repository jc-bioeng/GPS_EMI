"""Explicit consent, owner isolation and fixed-identity admission; offline only."""
from dataclasses import replace

import pytest

from gps_emi.selection import SelectionOperation
from gps_emi.sites import EMI_SITES
from test_watch_management import runtime, send, NUMBER


def offer_inside(runtime):
    service, watches, source, messenger = runtime
    source.get_vehicles.return_value = [replace(source.get_vehicles.return_value[0], zones=[EMI_SITES[0]])]
    send(service, 'VIGILAR AMB-20')
    watches.polling.cycle()
    command = service.vehicle_choices[NUMBER][0]
    selection_id = command.split()[1].split(':')[0]
    return service.selections.view(NUMBER, selection_id), command


@pytest.mark.parametrize('command', ['MENU', 'CANCELAR', '2', 'UBICACION AMB-20'])
def test_new_operation_invalidates_confirmation(runtime, command):
    service, watches, _, _ = runtime
    _, old = offer_inside(runtime)
    send(service, command)
    send(service, old)
    watches.polling.cycle()
    assert not watches.list_active(NUMBER)


def test_expiration_and_replay_do_not_admit(runtime):
    service, watches, _, messenger = runtime
    context, command = offer_inside(runtime)
    assert context.operation == SelectionOperation.CONFIRM_WATCH
    service.selections.now = lambda: context.created_at + 300
    send(service, '1')
    assert 'expiró' in messenger.client.send_text.call_args.args[1]
    send(service, command)
    watches.polling.cycle()
    assert not watches.list_active(NUMBER)


def test_confirmation_is_single_use_and_bound_to_id(runtime):
    service, watches, source, _ = runtime
    context, command = offer_inside(runtime)
    original = source.get_vehicles.return_value[0]
    source.get_vehicles.return_value = [replace(original, plate='RENAMED', mobile_number='RENAMED')]
    send(service, '1')
    watches.polling.cycle()
    assert [w.vehicle_id for w in watches.list_active(NUMBER)] == [original.vehid]
    send(service, command)
    watches.polling.cycle()
    assert len(watches.list_active(NUMBER)) == 1


@pytest.mark.parametrize('replacement', ['missing', 'duplicate'])
def test_revalidate_selected_identity_before_admission(runtime, replacement):
    service, watches, source, _ = runtime
    offer_inside(runtime)
    source.get_vehicles.return_value = ([] if replacement == 'missing' else source.get_vehicles.return_value * 2)
    send(service, '1')
    watches.polling.cycle()
    assert not watches.list_active(NUMBER)


def test_other_authorized_owner_cannot_accept(runtime):
    service, watches, _, _ = runtime
    _, command = offer_inside(runtime)
    other = '15555550102'
    service.config = replace(service.config, allowed_numbers=frozenset({NUMBER, other}))
    send(service, command, sender=other)
    watches.polling.cycle()
    assert not watches.list_active(other)
    assert not watches.list_active(NUMBER)
    send(service, '1')
    watches.polling.cycle()
    assert len(watches.list_active(NUMBER)) == 1


def test_ambiguous_label_requires_selection_then_confirmation(runtime):
    service, watches, source, _ = runtime
    source.get_vehicles.return_value = [replace(v, plate='SAME', zones=[EMI_SITES[1]]) for v in source.get_vehicles.return_value]
    send(service, 'VIGILAR SAME')
    watches.polling.cycle()
    send(service, '2')
    watches.polling.cycle()
    assert not watches.list_active(NUMBER)
    send(service, '1')
    watches.polling.cycle()
    assert [w.vehicle_id for w in watches.list_active(NUMBER)] == ['2']


def test_cancel_after_acceptance_before_polling_prevents_creation(runtime):
    service, watches, _, _ = runtime
    offer_inside(runtime)
    send(service, '1')
    send(service, 'CANCELAR')
    watches.polling.cycle()
    assert not watches.list_active(NUMBER)


def test_duplicate_active_watch_does_not_request_consent_again(runtime):
    service, watches, _, messenger = runtime
    offer_inside(runtime)
    send(service, '1')
    watches.polling.cycle()
    send(service, 'VIGILAR AMB-20')
    watches.polling.cycle()
    assert len(watches.list_active(NUMBER)) == 1
    assert 'ya tiene una vigilancia activa' in messenger.client.send_text.call_args.args[1]
