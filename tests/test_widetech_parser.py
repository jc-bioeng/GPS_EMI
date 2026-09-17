from datetime import datetime
import uuid

import pytest
import requests

from gps_emi.providers import widetech as wt

SAMPLE = r"""{'Rows': [
{'Sensors': [{'GPSFix': 99, 'Location': 'nested } ], {', 'Zones': 'wrong'}],
 'VEHID': 106, 'VEH_LCNS': 'AMB-106', 'VEH_NAM': 'Fallback',
 'Fecha': new Date(2026,8,17,10,22,31), 'FechaInsert': null,
 'Location': '<b>Medellín</b>, O\'Brien {calle}; "sur"',
 'Velocidad': 12.5, 'GPSFix': 0, 'StateIgnition': true,
 'Zones': ' Z - {ZONA 2 - POBLADO}; Z - {EMI_Medellin_Taller}',
 'fltName': 'Ambulancias Medellin;44986;0'},
{'VEHID': 999, 'VEH_LCNS': 'OTHER', 'fltName': 'Otra flota', 'Zones': ''}
]}"""


def test_observed_fields_and_normalization():
    rows = wt.parse(SAMPLE)
    assert len(rows) == 2
    row = rows[0]
    assert row['VEHID'] == 106
    assert row['VEH_LCNS'] == 'AMB-106'
    assert row['Fecha'] == datetime(2026, 9, 17, 10, 22, 31)
    assert row['Location'] == '<b>Medellín</b>, O\'Brien {calle}; "sur"'
    assert row['Velocidad'] == 12.5
    assert row['GPSFix'] == 0
    assert row['StateIgnition'] is True
    assert row['fltName'] == wt.TARGET_FLEET
    assert row['Zones'] == ' Z - {ZONA 2 - POBLADO}; Z - {EMI_Medellin_Taller}'
    vehicle = wt.normalize_vehicle(row)
    assert vehicle.vehid == '106'
    assert vehicle.plate == 'AMB-106'
    assert vehicle.mobile_name == 'Fallback'
    assert vehicle.gps_timestamp == row['Fecha']
    assert vehicle.location == row['Location']
    assert vehicle.speed == 12.5
    assert vehicle.gps_fix == 0
    assert vehicle.ignition is True
    assert vehicle.zones == ['ZONA 2 - POBLADO', 'EMI_Medellin_Taller']


def test_double_quotes_empty_and_fallback():
    row = wt.parse('{"Rows":[{"VEHID":1,"VEH_NAM":"amb-106","Zones":null}]}')[0]
    assert wt.normalize_vehicle(row).plate == ''
    assert wt.normalize_vehicle(row).mobile_name == 'amb-106'
    assert wt.normalize_vehicle(row).display_identifier == 'amb-106'
    assert wt.normalize_vehicle(row).zones == []
    assert wt.parse("{'Rows':[]}") == []


@pytest.mark.parametrize('sample', ['<html>login</html>', "{'Rows':[{'VEHID':1}", "{'Rows':[{'Location':'broken}"])
def test_malformed_response(sample):
    with pytest.raises(ValueError):
        wt.parse(sample)


def response(text, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = text.encode('utf-8')
    result.encoding = 'utf-8'
    result._content_consumed = True
    return result


def test_http_contract_and_fleet_filter(monkeypatch):
    # Valor efímero generado en memoria: no se almacena una cookie en fixtures.
    monkeypatch.setenv('GPSPACE_COOKIE', uuid.uuid4().hex)
    def post(url, **kwargs):
        assert url == wt.URL
        assert kwargs['params'] == {'_method': 'LoadDataLog', '_session': 'rw'}
        assert kwargs['data'] == ('Parameters=' + wt.PARAMETERS).encode('utf-8')
        assert bool(kwargs['headers']['Cookie'])
        assert kwargs['headers']['Content-Type'] == 'text/plain;charset=UTF-8'
        assert kwargs['timeout'] == 60
        assert kwargs['allow_redirects'] is False
        return response(SAMPLE)
    monkeypatch.setattr(wt.requests, 'post', post)
    vehicles = wt.WideTechClient().get_vehicles()
    assert [v.plate for v in vehicles] == ['AMB-106']


def test_missing_authentication():
    with pytest.raises(wt.WideTechError, match='Falta la variable'):
        wt.WideTechClient().get_vehicles()


@pytest.mark.parametrize('failure,expected', [
    ('network', 'No se pudo conectar'),
    ('status', 'HTTP 500'),
    ('authentication', 'sesión de GPSpace no es válida'),
    ('redirect', 'sesión de GPSpace no es válida'),
    ('login', 'sesión puede haber expirado'),
])
def test_safe_and_actionable_errors(monkeypatch, failure, expected):
    marker = uuid.uuid4().hex
    monkeypatch.setenv('GPSPACE_COOKIE', marker)
    def post(*args, **kwargs):
        if failure == 'network':
            raise requests.RequestException(marker)
        return response(marker, {
            'status': 500, 'authentication': 401, 'redirect': 302, 'login': 200,
        }[failure])
    monkeypatch.setattr(wt.requests, 'post', post)
    with pytest.raises(wt.WideTechError) as caught:
        wt.WideTechClient().get_vehicles()
    assert marker not in str(caught.value)
    assert caught.value.__context__ is None
    assert expected in str(caught.value)

