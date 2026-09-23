import hashlib
import hmac
import json
from dataclasses import replace
from threading import Event, Thread
from unittest.mock import Mock

import pytest

from gps_emi.whatsapp.webhook import create_app, IncomingMessage, MAX_BODY_BYTES
from gps_emi.whatsapp.worker import Inbox
from gps_emi.whatsapp.service import MessageService


def payload(config, *, text='MENU', sender='15555550101', identifier='wamid.one'):
    return {'object': 'whatsapp_business_account', 'entry': [{'changes': [{'field': 'messages', 'value': {
        'metadata': {'phone_number_id': config.phone_number_id},
        'messages': [{'id': identifier, 'from': sender, 'timestamp': '1000000',
                      'type': 'text', 'text': {'body': text}}],
    }}]}]}


def post(client, config, data, signature=None):
    body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
    signature = signature or 'sha256=' + hmac.new(config.app_secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post('/webhook', data=body, headers={'X-Hub-Signature-256': signature}, content_type='application/json')


def test_get_challenge_and_logs(wa_config, caplog):
    inbox = Mock()
    client = create_app(wa_config, inbox).test_client()
    result = client.get('/webhook', query_string={'hub.mode': 'subscribe', 'hub.verify_token': wa_config.verify_token,
                                                  'hub.challenge': '123456'})
    assert result.status_code == 200 and result.text == '123456'
    assert result.mimetype == 'text/plain'
    assert wa_config.verify_token not in caplog.text
    inbox.submit.assert_not_called()


@pytest.mark.parametrize('mode,token,challenge', [('subscribe', 'wrong', '1'), ('bad', '', '1'),
                                               ('subscribe', '', '')])
def test_bad_verification(wa_config, mode, token, challenge):
    client = create_app(wa_config, Mock()).test_client()
    assert client.get('/webhook', query_string={'hub.mode': mode, 'hub.verify_token': token,
                                               'hub.challenge': challenge}).status_code == 403


@pytest.mark.parametrize('signature', [None, '', 'sha1=123', 'sha256=wrong', 'sha256=á'])
def test_invalid_signature_never_enqueues(wa_config, signature):
    inbox = Mock()
    client = create_app(wa_config, inbox).test_client()
    headers = {'X-Hub-Signature-256': signature} if signature is not None else {}
    assert client.post('/webhook', json=payload(wa_config), headers=headers).status_code == 403
    inbox.submit.assert_not_called()


@pytest.mark.parametrize('data', [b'not-json', b'[]', b'null', b'"text"', b'\xff'])
def test_invalid_signed_payload(wa_config, data):
    inbox = Mock()
    client = create_app(wa_config, inbox).test_client()
    assert post(client, wa_config, data).status_code == 400
    inbox.submit.assert_not_called()


@pytest.mark.parametrize('change', ['status', 'image', 'wrong_phone', 'missing_text', 'bad_timestamp', 'wrong_object'])
def test_valid_irrelevant_events_ignored(wa_config, change):
    data = payload(wa_config)
    value = data['entry'][0]['changes'][0]['value']
    if change == 'status':
        value.pop('messages')
        value['statuses'] = [{'status': 'delivered'}]
    elif change == 'image':
        value['messages'][0]['type'] = 'image'
    elif change == 'wrong_phone':
        value['metadata']['phone_number_id'] = '999'
    elif change == 'missing_text':
        value['messages'][0]['text'] = None
    elif change == 'bad_timestamp':
        value['messages'][0]['timestamp'] = 'nan'
    else:
        data['object'] = 'other'
    handler = Mock()
    inbox = Inbox(handler, now=lambda: 0)
    client = create_app(wa_config, inbox).test_client()
    assert post(client, wa_config, data).status_code == 200
    assert not inbox.process_one()
    handler.assert_not_called()


@pytest.mark.parametrize('data', [{}, {'object': 'whatsapp_business_account', 'entry': None},
    {'object': 'whatsapp_business_account', 'entry': [None, {'changes': [1, {'field': 'messages', 'value': None}]}]}])
def test_other_valid_shapes(wa_config, data):
    inbox = Inbox(Mock(), now=lambda: 0)
    assert post(create_app(wa_config, inbox).test_client(), wa_config, data).status_code == 200
    assert not inbox.pending


def test_body_limit(wa_config):
    client = create_app(wa_config, Mock()).test_client()
    assert client.post('/webhook', data=b'x' * (MAX_BODY_BYTES + 1)).status_code == 413


def test_raw_bytes_signature_not_reserialized(wa_config):
    inbox = Inbox(Mock(), now=lambda: 0)
    client = create_app(wa_config, inbox).test_client()
    body = json.dumps(payload(wa_config, text='MENÚ'), ensure_ascii=False, indent=2).encode()
    signature = 'sha256=' + hmac.new(wa_config.app_secret.encode(), body, hashlib.sha256).hexdigest()
    assert post(client, wa_config, body, signature).status_code == 200
    assert post(client, wa_config, body + b' ', signature).status_code == 403


def test_duplicate_webhook_one_query_one_response(wa_config, messenger):
    from gps_emi.models import Vehicle
    source = Mock()
    source.get_vehicles.return_value = [Vehicle('433909', 'PJU886', mobile_number='AMB-20')]
    service = MessageService(wa_config, messenger, Mock(), lambda: source)
    inbox = Inbox(service.handle, now=lambda: 0)
    client = create_app(wa_config, inbox).test_client()
    data = payload(wa_config, text='UBICACION AMB-20')
    assert post(client, wa_config, data).status_code == 200
    assert post(client, wa_config, data).status_code == 200
    source.get_vehicles.assert_not_called()  # Handler solo encola.
    assert inbox.process_one() and not inbox.process_one()
    assert post(client, wa_config, data).status_code == 200
    assert not inbox.process_one()
    source.get_vehicles.assert_called_once()
    assert messenger.client.send_text.call_count == 2  # Feedback y resultado, una sola vez.


def test_unauthorized_webhook_end_to_end(wa_config, messenger):
    source, watches = Mock(), Mock()
    service = MessageService(wa_config, messenger, watches, source)
    inbox = Inbox(service.handle, now=lambda: 0)
    client = create_app(wa_config, inbox).test_client()
    assert post(client, wa_config, payload(wa_config, sender='15555550102', text='SEDE TALLER')).status_code == 200
    inbox.process_one()
    source.assert_not_called()
    watches.start.assert_not_called()
    assert 'no está autorizado' in messenger.client.send_text.call_args.args[1]


def test_busy_response_does_not_remember_rejected_message(wa_config):
    inbox = Inbox(Mock(), capacity=1, now=lambda: 0)
    client = create_app(wa_config, inbox).test_client()
    assert post(client, wa_config, payload(wa_config)).status_code == 200
    assert post(client, wa_config, payload(wa_config, identifier='second')).status_code == 503
    assert 'second' not in inbox.seen
    inbox.process_one()
    assert post(client, wa_config, payload(wa_config, identifier='second')).status_code == 200


def test_fifo_dedup_batch_atomic_and_expiry():
    clock = [0]
    handler = Mock()
    inbox = Inbox(handler, capacity=2, seen_capacity=2, ttl=7, now=lambda: clock[0])
    a = IncomingMessage('a', '15555550101', '1', 1000000)
    b = replace(a, message_id='b', text='AMB-20')
    assert inbox.submit([a, b, a])
    assert inbox.process_one() and inbox.process_one()
    assert [c.args[0] for c in handler.call_args_list] == [a, b]
    assert not inbox.submit([replace(a, message_id='c')])  # IDs no se expulsan prematuramente.
    clock[0] = 7
    assert inbox.submit([a])
    inbox.close(timeout=0)
    assert not inbox.submit([b]) and not inbox.process_one()


def test_concurrent_duplicate_only_once():
    inbox = Inbox(Mock(), now=lambda: 0)
    message = IncomingMessage('a', '15555550101', 'MENU', 1000000)
    threads = [Thread(target=lambda: inbox.submit([message])) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1)
    assert len(inbox.pending) == 1


def test_worker_lifecycle_no_sleep():
    processed = Event()
    inbox = Inbox(lambda message: processed.set(), now=lambda: 0)
    inbox.start()
    try:
        inbox.submit([IncomingMessage('a', '15555550101', 'MENU', 1000000)])
        assert processed.wait(timeout=1)
    finally:
        assert inbox.close(timeout=1)


def test_worker_error_is_safe_and_next_message_runs(wa_config, caplog):
    handler = Mock(side_effect=[RuntimeError(wa_config.access_token), None])
    inbox = Inbox(handler, now=lambda: 0)
    inbox.submit([IncomingMessage(str(i), '15555550101', 'MENU', 1000000) for i in range(2)])
    assert inbox.process_one() and inbox.process_one()
    assert handler.call_count == 2
    assert wa_config.access_token not in caplog.text


def test_duplicate_watch_starts_once(wa_config, messenger):
    watches, source = Mock(), Mock()
    service = MessageService(wa_config, messenger, watches, source)
    inbox = Inbox(service.handle, now=lambda: 0)
    client = create_app(wa_config, inbox).test_client()
    data = payload(wa_config, text='VIGILAR PJU886')
    for _ in range(3):
        assert post(client, wa_config, data).status_code == 200
        inbox.process_one()
    watches.start.assert_called_once_with('15555550101', 'PJU886')
    source.assert_not_called()


def test_batch_full_rejection_is_atomic():
    inbox = Inbox(Mock(), capacity=1, now=lambda: 0)
    a = IncomingMessage('a', '15555550101', 'MENU', 1000000)
    assert not inbox.submit([a, replace(a, message_id='b')])
    assert not inbox.pending and not inbox.seen


def test_webhook_internal_errors_do_not_leak(wa_config, caplog):
    inbox = Mock()
    inbox.submit.side_effect = RuntimeError(wa_config.app_secret)
    client = create_app(wa_config, inbox).test_client()
    result = post(client, wa_config, payload(wa_config))
    assert result.status_code == 500
    assert wa_config.app_secret not in result.text + caplog.text
    assert all(record.exc_info is None for record in caplog.records)
