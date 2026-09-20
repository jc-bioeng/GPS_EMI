from dataclasses import replace
import json
from unittest.mock import Mock

import pytest
import requests

from gps_emi.whatsapp.client import WhatsAppClient, WhatsAppError
from gps_emi.whatsapp.config import WhatsAppConfig, WhatsAppConfigError, normalize_number
from gps_emi.whatsapp.delivery import ServiceWindow, Messenger, split_text


def response(status=200, body=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body if body is not None else {'messages': [{'id': 'wamid.test'}]}).encode()
    result._content_consumed = True
    return result


def test_text_and_template_http_contract(wa_config, caplog):
    post = Mock(side_effect=[response(), response()])
    client = WhatsAppClient(wa_config, post=post)
    assert client.send_text('+1 555 555 0101', 'MENU') == 'wamid.test'
    args, kw = post.call_args
    assert args == ('https://graph.facebook.com/v25.0/123456789/messages',)
    assert kw['headers']['Authorization'] == 'Bearer ' + wa_config.access_token
    assert kw['timeout'] == (5, 20) and kw['allow_redirects'] is False
    assert kw['json'] == {'messaging_product': 'whatsapp', 'recipient_type': 'individual',
                          'to': '15555550101', 'type': 'text', 'text': {'body': 'MENU', 'preview_url': False}}
    client.send_template('15555550101', 'ambulance_arrival_notification', 'es', ['AMB-20', 'PJU886', 'Sede', 'Fecha'])
    template = post.call_args.kwargs['json']['template']
    assert template['name'] == 'ambulance_arrival_notification'
    assert template['language'] == {'code': 'es'}
    assert template['components'][0]['parameters'] == [
        {'type': 'text', 'text': value} for value in ['AMB-20', 'PJU886', 'Sede', 'Fecha']]
    assert wa_config.access_token not in caplog.text
    assert 'entrega no confirmada' in caplog.text


@pytest.mark.parametrize('status,category', [(401, 'authentication'), (403, 'authentication'),
    (429, 'http'), (500, 'http'), (503, 'http'), (302, 'http'), (400, 'http')])
def test_http_errors_safe_no_retry(wa_config, status, category, caplog):
    post = Mock(return_value=response(status, {'error': wa_config.access_token}))
    with pytest.raises(WhatsAppError) as caught:
        WhatsAppClient(wa_config, post=post).send_text('15555550101', 'test')
    assert caught.value.category == category and caught.value.status == status
    assert wa_config.access_token not in str(caught.value) + caplog.text
    post.assert_called_once()


@pytest.mark.parametrize('exception,category', [(requests.Timeout, 'timeout'),
    (requests.ConnectionError, 'connection'), (requests.RequestException, 'transport')])
def test_network_errors_are_detached(wa_config, exception, category, caplog):
    post = Mock(side_effect=exception(wa_config.access_token))
    with pytest.raises(WhatsAppError) as caught:
        WhatsAppClient(wa_config, post=post).send_text('15555550101', 'test')
    assert caught.value.category == category
    assert caught.value.__context__ is None
    assert wa_config.access_token not in caplog.text + str(caught.value)


@pytest.mark.parametrize('body', [{}, [], {'messages': []}, {'messages': [None]},
                                 {'messages': [{'id': ''}]}, {'messages': [{'id': 1}]}])
def test_unexpected_json(wa_config, body):
    with pytest.raises(WhatsAppError, match='unexpected_response'):
        WhatsAppClient(wa_config, post=Mock(return_value=response(body=body))).send_text('15555550101', 'test')


def test_non_json(wa_config):
    result = response()
    result._content = b'<html>invalid</html>'
    with pytest.raises(WhatsAppError, match='unexpected_response'):
        WhatsAppClient(wa_config, post=Mock(return_value=result)).send_text('15555550101', 'test')


@pytest.mark.parametrize('text', ['', ' ', 'a' * 4097, None])
def test_bad_text_rejected_before_http(wa_config, text):
    post = Mock()
    with pytest.raises(WhatsAppError, match='configuration'):
        WhatsAppClient(wa_config, post=post).send_text('15555550101', text)
    post.assert_not_called()


@pytest.mark.parametrize('value', ['+1 (555) 555-0101', '15555550101', ' 15555550101 '])
def test_number_normalization(value):
    assert normalize_number(value) == '15555550101'


@pytest.mark.parametrize('value', ['', '123', 'abc15555550101', '0015555550101', '1+5555550101', '１２３４５６７８９'])
def test_bad_number(value):
    with pytest.raises(WhatsAppConfigError):
        normalize_number(value)


@pytest.mark.parametrize('field,value', [('access_token', ''), ('app_secret', ''), ('verify_token', ''),
    ('phone_number_id', '../messages'), ('api_version', 'v25.0/evil'), ('allowed_numbers', frozenset()),
    ('arrival_mode', 'anything'), ('template_name', 'Bad name'), ('template_language', 'bad-language')])
def test_config_fails_closed(wa_config, field, value):
    with pytest.raises(WhatsAppConfigError):
        replace(wa_config, **{field: value})


def test_env_and_safe_repr(wa_config):
    env = {'WHATSAPP_ACCESS_TOKEN': wa_config.access_token, 'WHATSAPP_APP_SECRET': wa_config.app_secret,
           'WHATSAPP_VERIFY_TOKEN': wa_config.verify_token, 'WHATSAPP_PHONE_NUMBER_ID': '12345',
           'WHATSAPP_ALLOWED_NUMBERS': '+1 555 555 0101,15555550102', 'WHATSAPP_API_VERSION': 'v26.0'}
    config = WhatsAppConfig.from_env(env)
    assert config.allowed_numbers == frozenset({'15555550101', '15555550102'})
    assert 'v26.0' in WhatsAppClient(config).endpoint
    for secret in (config.access_token, config.verify_token, config.app_secret):
        assert secret not in repr(config)
    with pytest.raises(WhatsAppConfigError):
        WhatsAppConfig.from_env({})


def test_service_window_uses_inbound_time_not_processing_time():
    now = [1000000]
    window = ServiceWindow(now=lambda: now[0])
    assert not window.note('a', now[0] - 86400)
    assert window.note('a', now[0] - 86399)
    now[0] += 1
    assert not window.is_open('a')
    assert window.note('a', now[0])
    assert window.note('a', now[0] - 90000)  # Nunca retrocede la ventana de mensaje más reciente.
    assert not window.note('b', now[0] + 61)


def test_chunking_and_closed_window_no_http(messenger):
    text = ('línea\n' * 2000).rstrip('\n')
    messenger.windows.note('15555550101', 1000000)
    messenger.reply('15555550101', text)
    chunks = [call.args[1] for call in messenger.client.send_text.call_args_list]
    assert all(len(part) <= 4096 for part in chunks)
    assert '\n'.join(chunks) == text
    assert list(split_text('x' * 5000)) == ['x' * 4096, 'x' * 904]
    messenger.client.reset_mock()
    with pytest.raises(WhatsAppError, match='service_window_closed'):
        messenger.reply('15555550102', 'test')
    messenger.client.send_text.assert_not_called()
