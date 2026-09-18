import uuid

import pytest
import requests

from gps_emi.errors import (
    AcquisitionError, TransientAcquisitionError, SessionExpiredError,
    InvalidResponseError, HTTPAcquisitionError, MissingCredentialsError,
)
from gps_emi.providers.widetech import WideTechClient


@pytest.fixture
def stub_response(monkeypatch):
    marker = uuid.uuid4().hex
    monkeypatch.setenv('GPSPACE_COOKIE', marker)
    def install(status=200, body="{'Rows': []}"):
        response = requests.Response()
        response.status_code = status
        response._content = body.encode('utf-8')
        response._content_consumed = True
        response.encoding = 'utf-8'
        monkeypatch.setattr('requests.post', lambda *args, **kwargs: response)
        return response
    return install


@pytest.mark.parametrize('status', [408, 429, 500, 502, 503, 504])
def test_recoverable_http_statuses(stub_response, status):
    stub_response(status)
    with pytest.raises(TransientAcquisitionError) as caught:
        WideTechClient().get_vehicles()
    assert f'HTTP {status}' in caught.value.public_message
    assert caught.value.__context__ is None


@pytest.mark.parametrize('status', [400, 404, 405, 501, 505])
def test_other_http_statuses_are_not_retried(stub_response, status):
    stub_response(status)
    with pytest.raises(HTTPAcquisitionError) as caught:
        WideTechClient().get_vehicles()
    assert not isinstance(caught.value, TransientAcquisitionError)


@pytest.mark.parametrize('status', [301, 302, 307, 401, 403])
def test_authentication_statuses_terminate(stub_response, status):
    stub_response(status)
    with pytest.raises(SessionExpiredError):
        WideTechClient().get_vehicles()


@pytest.mark.parametrize('body', [
    '<html><input type="password"></html>',
    '<html>Login</html>',
    '{"error":"Session expired"}',
    "{'error':'sesión expirada'}",
    'Unauthorized',
])
def test_authentication_failure_with_http_200(stub_response, body):
    stub_response(body=body)
    with pytest.raises(SessionExpiredError):
        WideTechClient().get_vehicles()


def test_login_text_inside_vehicle_location_is_not_authentication_failure(stub_response):
    stub_response(body="""{'Rows':[{'VEHID':1,'VEH_LCNS':'AMB-20','VEH_NAM':'PJU886',
        'fltName':'Ambulancias Medellin;44986;0', 'Location':'Login street'}]}""")
    assert WideTechClient().get_vehicles()[0].location == 'Login street'


@pytest.mark.parametrize('body', ['', '  \n'])
def test_empty_endpoint_body_is_transient(stub_response, body):
    stub_response(body=body)
    with pytest.raises(TransientAcquisitionError):
        WideTechClient().get_vehicles()


@pytest.mark.parametrize('body', ['unexpected format', "{'Rows':[{'VEHID':1}"])
def test_unknown_or_malformed_format_is_not_retried_indefinitely(stub_response, body):
    stub_response(body=body)
    with pytest.raises(InvalidResponseError):
        WideTechClient().get_vehicles()


def test_no_credentials_terminates_without_http(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('No debe consultar sin configuración de autenticación')
    monkeypatch.setattr(requests, 'post', unexpected)
    with pytest.raises(MissingCredentialsError):
        WideTechClient().get_vehicles()


@pytest.mark.parametrize('error_type,recoverable', [
    (requests.Timeout, True), (requests.ConnectionError, True),
    (requests.exceptions.ChunkedEncodingError, True),
    (requests.exceptions.ContentDecodingError, True),
    (requests.RequestException, False),
])
def test_transport_errors_are_classified_and_sanitized(monkeypatch, error_type, recoverable):
    marker = uuid.uuid4().hex
    monkeypatch.setenv('GPSPACE_COOKIE', marker)
    def post(*args, **kwargs):
        raise error_type(marker)
    monkeypatch.setattr(requests, 'post', post)
    with pytest.raises(AcquisitionError) as caught:
        WideTechClient().get_vehicles()
    assert isinstance(caught.value, TransientAcquisitionError) == recoverable
    assert marker not in str(caught.value)
    assert marker not in caught.value.public_message
    assert caught.value.__context__ is None
