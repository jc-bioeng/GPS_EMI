"""Vectores sintéticos contrastados con el algoritmo JavaScript en Node.js."""
import base64
import json

import pytest
import requests

from gps_emi.errors import AcquisitionError, TransientAcquisitionError
from gps_emi.providers import widetech
from gps_emi.providers.load_data_log import (
    STATE_FIELDS, LoadDataLogConfigError, LoadDataLogState, WideTechSessionInfo,
    _get_obfuscation_key_byte, build_parameters, generate_parameters,
    obfuscate_string, serialize_parameters,
)


REQUEST_GOLDEN = (
    "8LpeZcTdi4FJwVf2LNxryHuq9YStTKM7IYF_xrcvfjg7MbeGDMWUUopBSMX3b1a5"
    "uGHgN_9FdAMSinj2bn7tSfg4cgUunrR7w0JxwvRs3RTbitG4R3Yd9luLeXgH7aRO"
    "O9NxGUefp4yk2_pBNa3mTQQD8IOoT6as_JQ6Q3JipU-0DIK4-JAXVMx-AcC4sDd-7"
    "QQz2vlSrwZFfUEws2FgzlQ9WyopyQm2xv0cwfNr2BfejdS7QnEY9RZ-HGvqitO3"
)


@pytest.mark.parametrize("key,index,expected", [
    ("K", 0, 92), ("AB", 2, 144), ("K", 100, 120),
    ("", 0, 136), ("🗝", 0, 78), ("🗝", 1, 13),
])
def test_key_byte(key, index, expected):
    assert _get_obfuscation_key_byte(key, index) == expected


@pytest.mark.parametrize("text,key,expected", [
    ('{"test":123,"hello":"GPS_EMI"}', "TEST_KEY", "8Lq2Pfwckctj-k20NjxruslQhUT3BYIDkMA-H7cV"),
    ("Ambulancia ñ 🚑", "CLAVE_🗝", "qIiXjfVTMyUpqEX72xmHAfbv"),
    ("abc", "", "Tzaf"), ("A", "K", "6A"), ("", "K", ""),
])
def test_independent_javascript_goldens(text, key, expected):
    assert obfuscate_string(text, key) == expected


def test_fallback_and_rotation():
    assert obfuscate_string("abc", "") == obfuscate_string("abc", "wtApi")
    # 65 XOR (75 + 17) = 29; rotación de tres bits = 232.
    assert base64.urlsafe_b64decode(obfuscate_string("A", "K") + "==") == b"\xe8"


def test_parameters_order_types_and_session_roles():
    state = LoadDataLogState.from_env()
    session = WideTechSessionInfo.from_env()
    parameters = build_parameters(session, state)
    assert list(parameters) == [
        "intLastUpdate", "intTimer", "strMobiles", "intConsoleType", "idFleet",
        "bolAddDriver", "intFrom", "strUserID", "strOriginQuery",
    ]
    assert parameters["strUserID"] == session.uid
    assert parameters["bolAddDriver"] is True
    assert parameters["idFleet"] == "synthetic-fleet"
    assert session.uname not in serialize_parameters(parameters)
    other = WideTechSessionInfo(session.uid, "OTHER_KEY")
    assert build_parameters(other, state) == parameters
    assert generate_parameters(other, state) != generate_parameters(session, state)
    assert generate_parameters(session, state) == REQUEST_GOLDEN
    assert "-" in REQUEST_GOLDEN and "_" in REQUEST_GOLDEN
    assert not any(char in REQUEST_GOLDEN for char in "+/=")


@pytest.mark.parametrize("uid", ["00123", 123])
def test_uid_preserves_observed_json_type(uid):
    session = WideTechSessionInfo.from_env({"GPSPACE_SESSION_INFO": json.dumps({"UID": uid, "UNAME": ""})})
    assert build_parameters(session, LoadDataLogState.from_env())["strUserID"] == uid
    assert type(session.uid) is type(uid)


def test_compact_unicode_json():
    assert serialize_parameters({"a": "ñ 🚑", "b": True, "c": None, "d": '"\n'}) == '{"a":"ñ 🚑","b":true,"c":null,"d":"\\\"\\n"}'
    assert serialize_parameters({"s": "\ud83d\ude91"}) == '{"s":"🚑"}'
    text = serialize_parameters({"strOriginQuery": "\ud800"})
    assert text == '{"strOriginQuery":"\\ud800"}'
    assert obfuscate_string(text, "TEST_KEY") == "8LqOtfTFE1HRIKdfjFTTErv6hXdNHMEY6_u_"


@pytest.mark.parametrize("raw", ["", "private-invalid-json", "null", "[]", "{}", '{"UID":"x","UNAME":"k","extra":1}', '{"UID":"x","UID":"y","UNAME":"k"}'])
def test_invalid_session_is_sanitized(raw, caplog):
    with pytest.raises(LoadDataLogConfigError) as caught:
        WideTechSessionInfo.from_env({"GPSPACE_SESSION_INFO": raw})
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert "private-invalid-json" not in str(caught.value) + caplog.text
    assert isinstance(caught.value, AcquisitionError)
    assert not isinstance(caught.value, TransientAcquisitionError)


@pytest.mark.parametrize("uid,uname", [(True,"k"), (None,"k"), (" ","k"), (2**53,"k"), (1.5,"k"), ("x",None)])
def test_invalid_session_types(uid, uname):
    with pytest.raises(LoadDataLogConfigError):
        WideTechSessionInfo(uid, uname)


@pytest.mark.parametrize("field", STATE_FIELDS)
def test_every_state_field_is_required(field):
    state = LoadDataLogState.from_env()
    values = {name: getattr(state, name) for name in STATE_FIELDS if name != field}
    with pytest.raises(LoadDataLogConfigError):
        LoadDataLogState.from_env({"GPSPACE_LOADDATALOG_STATE": json.dumps(values)})


@pytest.mark.parametrize("value", [1.5, float("nan"), [], {}, 2**53])
def test_unsupported_state_values_rejected(value):
    values = dict(vars(LoadDataLogState.from_env()), intTimer=value)
    with pytest.raises(LoadDataLogConfigError):
        LoadDataLogState(**values)


def test_state_preserves_scalars_without_inference():
    values = dict(zip(STATE_FIELDS, [None, "007", "ñ", False, "another-fleet", 0, ""]))
    state = LoadDataLogState.from_env({"GPSPACE_LOADDATALOG_STATE": json.dumps(values)})
    assert vars(state) == values
    assert "another-fleet" not in repr(state)
    assert "secret-key" not in repr(WideTechSessionInfo("private-user", "secret-key"))


def test_request_uses_dynamic_parameters(monkeypatch):
    monkeypatch.setenv("GPSPACE_COOKIE", "synthetic-cookie")
    bodies = []

    def post(url, **kwargs):
        assert url == widetech.URL
        assert kwargs["params"] == {"_method": "LoadDataLog", "_session": "rw"}
        assert kwargs["timeout"] == 60
        assert kwargs["allow_redirects"] is False
        bodies.append(kwargs["data"])
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"Rows":[]}'
        return response

    monkeypatch.setattr(widetech.requests, "post", post)
    client = widetech.LegacyWideTechTransport()
    assert client.load_data_log() == '{"Rows":[]}'
    assert bodies[0] == ("Parameters=" + REQUEST_GOLDEN).encode()
    client.load_data_log()
    assert bodies[1] == bodies[0]  # No inventar avance de intLastUpdate.
    monkeypatch.setenv("GPSPACE_SESSION_INFO", '{"UID":"other-user","UNAME":"OTHER_KEY"}')
    client.load_data_log()
    assert bodies[2] != bodies[0]


@pytest.mark.parametrize("variable", ["GPSPACE_SESSION_INFO", "GPSPACE_LOADDATALOG_STATE"])
def test_missing_configuration_fails_before_http(monkeypatch, variable):
    monkeypatch.setenv("GPSPACE_COOKIE", "synthetic-cookie")
    monkeypatch.delenv(variable)
    client = widetech.LegacyWideTechTransport()  # Configuración deliberadamente diferida.
    with pytest.raises(LoadDataLogConfigError):
        client.load_data_log()  # El fixture global prohíbe HTTP real.


def test_explicit_configuration_works_without_env(monkeypatch):
    session, state = WideTechSessionInfo.from_env(), LoadDataLogState.from_env()
    monkeypatch.delenv("GPSPACE_SESSION_INFO")
    monkeypatch.delenv("GPSPACE_LOADDATALOG_STATE")
    monkeypatch.setenv("GPSPACE_COOKIE", "synthetic-cookie")
    def post(*args, **kwargs):
        assert kwargs["data"] == ("Parameters=" + REQUEST_GOLDEN).encode()
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"Rows":[]}'
        return response
    monkeypatch.setattr(widetech.requests, "post", post)
    assert widetech.LegacyWideTechTransport(session_info=session, query_state=state).get_vehicles() == []
