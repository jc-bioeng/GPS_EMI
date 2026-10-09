from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
import traceback

import pytest
import requests

from gps_emi.providers import widetech_official as wt

FIXTURE = Path(__file__).parent / "fixtures" / "render_excel.xml"


def payload(rows=None, *, empty_diff=False):
    root = ET.fromstring(FIXTURE.read_bytes())
    diff = root.find(f"{{{wt.DIFF}}}diffgram")
    dataset = diff[0]
    template = deepcopy(dataset[0])
    dataset.clear()
    for changes in ([{}] if rows is None else rows):
        row = deepcopy(template)
        for name, value in changes.items():
            node = row.find(name)
            if node is not None:
                row.remove(node)
            if value == "ABSENT":
                continue
            node = ET.SubElement(row, name)
            if value is None:
                node.set(f"{{{wt.XSI}}}nil", "true")
            else:
                node.text = value
        dataset.append(row)
    if empty_diff:
        diff.clear()
    return ET.tostring(root, encoding="utf-8")


def response(body=None, status=200, headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = payload() if body is None else body
    result._content_consumed = True
    result.headers.update(headers or {})
    return result


class FakeTransport:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def client(result):
    transport = FakeTransport(result)
    return wt.OfficialWideTechClient(wt.OfficialConfig("synthetic-login", "synthetic-password"),
                                     transport=transport), transport


def test_realistic_fixture_contract():
    batch = wt.parse_render_excel(FIXTURE.read_bytes())
    record, = batch.records
    assert record.vehicle_id == "10001" and record.gps_record_id == "90001"
    assert record.raw["Movil"] == "SYNTHETIC-MOBILE-A"
    assert record.raw["VEH_NAM"] == "SYNTHETIC-LABEL-A"
    assert record.classification is wt.FleetClass.AMBULANCE
    assert record.raw["VEH_DESC"] == "CAMIONETA"
    assert record.gps_fix == "provider-value"
    assert (record.latitude, record.longitude, record.speed) == (0.125, 0.25, 12.5)
    assert record.ignition is False
    assert record.zones == ("Zona sintética",) and record.zones_present
    assert record.raw["StatusForm"] == "" and "mtlCelularID" not in record.raw
    assert not batch.has_quality_issues and batch.coverage == "unknown"
    assert record.source == batch.source == wt.SOURCE
    with pytest.raises(TypeError):
        record.raw["VEH_ID"] = "changed"


@pytest.mark.parametrize("empty_diff", [False, True])
def test_empty_dataset_is_valid_schema_never_becomes_rows(empty_diff):
    batch = wt.parse_render_excel(payload([], empty_diff=empty_diff))
    assert batch.records == () and batch.coverage == "unknown"
    assert not batch.has_quality_issues


def test_multiple_fleets_no_filter_or_reclassification_by_description():
    batch = wt.parse_render_excel(payload([
        {}, {"VEH_ID": "10002", "fltName": "Ambulancias Cartagena"},
        {"VEH_ID": "10003", "fltName": "Administración", "VEH_DESC": "AMBULANCIA"},
        {"VEH_ID": "10004", "fltName": None}]))
    assert [r.classification.value for r in batch.records] == ["ambulance", "ambulance", "other", "unknown"]
    assert batch.records[2].vehicle_id == "10003" and batch.incomplete_rows == (4,)


@pytest.mark.parametrize("name,normalized,expected", [
    (" Ambulancias Medellín\t", "Ambulancias Medellín", "ambulance"),
    ("Ambulancias Medelli\u0301n", "Ambulancias Medellín", "ambulance"),
    ("ambulancias Medellín", "ambulancias Medellín", "other"),
    ("AMBULANCIAS Medellín", "AMBULANCIAS Medellín", "other"),
    ("Ambulancia Medellín", "Ambulancia Medellín", "other"),
    ("AmbulanciasX", "AmbulanciasX", "ambulance"),
    ("Otras Ambulancias", "Otras Ambulancias", "other"),
    ("Ambulancias  Medellín", "Ambulancias  Medellín", "ambulance"),
    ("", "", "unknown"), (None, None, "unknown"),
])
def test_fleet_normalization_is_explicit(name, normalized, expected):
    record, = wt.parse_render_excel(payload([{"fltName": name}])).records
    assert record.raw["fltName"] == name and record.fleet_name == normalized
    assert record.classification.value == expected


@pytest.mark.parametrize("value,present,raw", [("ABSENT", False, None), (None, True, None), ("", True, "")])
def test_absent_nil_empty_and_unknown_fields(value, present, raw):
    record, = wt.parse_render_excel(payload([{
        "Zones": value, "Movil": value, "FechaServidor": value,
        "Extra": "ignored", "mtlCelularID": "never-retain"}])).records
    assert record.zones_present is present and record.raw.get("Zones") == raw
    assert record.zones == () and record.server_timestamp is None
    assert "Extra" not in record.raw and "mtlCelularID" not in record.raw
    assert not record.diagnostics


@pytest.mark.parametrize("name", ["Latitude", "Longitude", "Velocidad"])
@pytest.mark.parametrize("value", ["NaN", "inf", "-Infinity", "invalid", "1e9999", "1_2", "", None, "ABSENT"])
def test_invalid_and_missing_numbers_are_never_zero(name, value):
    record, = wt.parse_render_excel(payload([{name: value}])).records
    attr = {"Latitude": "latitude", "Longitude": "longitude", "Velocidad": "speed"}[name]
    assert getattr(record, attr) is None
    invalid = value not in ("", None, "ABSENT")
    assert any(d.code == "invalid_number" and d.field == name for d in record.diagnostics) is invalid


def test_no_geographical_or_motion_filters_and_zero_is_valid():
    record, = wt.parse_render_excel(payload([{"Latitude": "999", "Longitude": "-999", "Velocidad": "-8000"}])).records
    assert (record.latitude, record.longitude, record.speed) == (999, -999, -8000)
    assert not record.diagnostics
    record, = wt.parse_render_excel(payload([{"Latitude": "0", "Velocidad": "0"}])).records
    assert record.latitude == record.speed == 0 and not record.diagnostics


@pytest.mark.parametrize("value,expected", [("0", False), ("1", True), ("false", False), ("true", True), ("", None), (None, None), ("2", None)])
def test_explicit_ignition(value, expected):
    record, = wt.parse_render_excel(payload([{"StateIgnition": value}])).records
    assert record.ignition is expected
    assert any(d.code == "invalid_ignition" for d in record.diagnostics) is (value == "2")


def test_dates_original_and_configured_zone_no_fallback():
    for zone, offset in [("America/Bogota", -5), ("UTC", 0), ("Asia/Tokyo", 9)]:
        record, = wt.parse_render_excel(payload(), timezone_name=zone).records
        assert record.raw["FechaGPS"] == "2026-01-02T03:04:05.123"
        assert record.raw["FechaServidor"] == "2026-01-02T03:05:06"
        assert record.gps_timestamp.utcoffset() == timedelta(hours=offset)
        assert record.gps_timestamp.microsecond == 123000
        assert record.server_timestamp != record.gps_timestamp
    record, = wt.parse_render_excel(payload([{"FechaGPS": "ABSENT"}])).records
    assert record.gps_timestamp is None and record.server_timestamp is not None


@pytest.mark.parametrize("date", ["bad", "2026-02-30T01:02:03", "02/01/2026", "2026-01-02", "0001-01-01T00:00:00+14:00"])
def test_invalid_dates(date):
    record, = wt.parse_render_excel(payload([{"FechaGPS": date, "FechaServidor": date}])).records
    assert record.gps_timestamp is record.server_timestamp is None
    assert sum(d.code == "invalid_timestamp" for d in record.diagnostics) == 2
    assert record.raw["FechaGPS"] == date


@pytest.mark.parametrize("date", ["2026-01-02T03:04:05Z", "2026-01-02T05:04:05+02:00"])
def test_offset_dates_are_converted(date):
    record, = wt.parse_render_excel(payload([{"FechaGPS": date}])).records
    assert record.gps_timestamp.hour == 22 and record.gps_timestamp.day == 1


@pytest.mark.parametrize("date", ["2026-03-08T02:30:00", "2026-11-01T01:30:00"])
def test_dst_unknown_interpretation_is_diagnostic(date):
    record, = wt.parse_render_excel(payload([{"FechaGPS": date}]), timezone_name="America/New_York").records
    assert record.gps_timestamp is None
    assert any(d.code == "ambiguous_or_nonexistent_timestamp" for d in record.diagnostics)


def test_duplicate_and_missing_identity_retain_every_row():
    batch = wt.parse_render_excel(payload([{}, {"Id": "90002"}, {"VEH_ID": "ABSENT"}, {"VEH_ID": ""}]))
    assert len(batch.records) == 4 and batch.duplicate_ids == ("10001",)
    assert batch.incomplete_rows == (3, 4)
    assert [d.row for d in batch.diagnostics if d.code == "duplicate_identity"] == [1, 2]
    assert batch.records[2].gps_record_id == "90001" and batch.records[2].vehicle_id is None
    assert batch.has_quality_issues


@pytest.mark.parametrize("body,kind", [
    (b"", wt.ErrorKind.EMPTY), (b" \n", wt.ErrorKind.EMPTY),
    (b"<DataTable", wt.ErrorKind.PAYLOAD), (b"<unknown />", wt.ErrorKind.PAYLOAD),
    (b"<DataTable />", wt.ErrorKind.PAYLOAD),
    (b"<string xmlns='http://shareservice.co/'>109</string>", wt.ErrorKind.PAYLOAD),
])
def test_empty_truncated_unknown_are_not_empty_fleets(body, kind):
    with pytest.raises(wt.OfficialAcquisitionError) as caught:
        wt.parse_render_excel(body)
    assert caught.value.kind is kind and caught.value.__context__ is None


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_dtd_entities_forbidden_even_alternate_encoding(encoding):
    text = '<?xml version="1.0" encoding="' + encoding + '"?><!DOCTYPE DataTable [<!ENTITY secret SYSTEM "file:///secret">]><DataTable>&secret;</DataTable>'
    with pytest.raises(wt.OfficialAcquisitionError) as caught:
        wt.parse_render_excel(text.encode(encoding))
    assert caught.value.kind is wt.ErrorKind.PAYLOAD and caught.value.__context__ is None


@pytest.mark.parametrize("change", ["wrong_namespace", "before", "unknown_row", "no_schema", "two_diffgrams"])
def test_unknown_structure_never_claims_success(change):
    root = ET.fromstring(payload())
    diff = root.find(f"{{{wt.DIFF}}}diffgram")
    if change == "wrong_namespace":
        diff.tag = "diffgram"
    elif change == "before":
        ET.SubElement(diff, f"{{{wt.DIFF}}}before")
    elif change == "unknown_row":
        diff[0][0].tag = "OtherTable"
    elif change == "no_schema":
        root.remove(root[0])
    else:
        root.append(deepcopy(diff))
    with pytest.raises(wt.OfficialAcquisitionError):
        wt.parse_render_excel(ET.tostring(root))


def soap_fault(code="Server", message="synthetic-private-message"):
    return (f'<s:Envelope xmlns:s="{wt.SOAP_NAMESPACES[0]}"><s:Body><s:Fault>'
            f'<faultcode>{code}</faultcode><faultstring>{message}</faultstring>'
            '</s:Fault></s:Body></s:Envelope>').encode()


def test_soap_failure_does_not_invent_functional_code_mapping():
    for body, kind in [(soap_fault(), wt.ErrorKind.SOAP), (soap_fault("109"), wt.ErrorKind.SOAP),
                       (soap_fault("Server", "Error 109"), wt.ErrorKind.SOAP)]:
        with pytest.raises(wt.OfficialAcquisitionError) as caught:
            wt.parse_render_excel(body)
        assert caught.value.kind is kind
        assert caught.value.functional_code is None
        assert "synthetic-private" not in str(caught.value)
    record, = wt.parse_render_excel(payload([{"Mensaje": "Error 109", "Id": "109"}])).records
    assert record.gps_record_id == "109"


@pytest.mark.parametrize("soap", wt.SOAP_NAMESPACES)
def test_soap_response_wrapper(soap):
    root = ET.Element(f"{{{soap}}}Envelope")
    body = ET.SubElement(root, f"{{{soap}}}Body")
    res = ET.SubElement(body, f"{{{wt.NS}}}{wt.METHOD}Response")
    result = ET.SubElement(res, f"{{{wt.NS}}}{wt.METHOD}Result")
    result.extend(list(ET.fromstring(payload())))
    assert len(wt.parse_render_excel(ET.tostring(root)).records) == 1


def test_transport_contract_one_call_and_no_secrets(caplog):
    api, fake = client(response())
    assert len(api.acquire().records) == len(fake.calls) == 1
    url, kwargs = fake.calls[0]
    assert url == wt.ENDPOINT and "?" not in url
    assert kwargs["data"] == {"sLogin": "synthetic-login", "sPassword": "synthetic-password"}
    assert kwargs["allow_redirects"] is False and kwargs["timeout"] == (10, 30)
    assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert "Cookie" not in kwargs["headers"]
    assert "synthetic-password" not in repr(api.config) + repr(api) + caplog.text


@pytest.mark.parametrize("status,kind", [(401, "authentication"), (403, "authentication"), (429, "restriction"),
                                          (500, "http"), (502, "http"), (503, "http"), (599, "http"),
                                          (302, "http"), (307, "http"), (204, "http"), (400, "http")])
def test_http_errors_no_retries(status, kind, caplog):
    api, fake = client(response(b"synthetic-password", status, {"Retry-After": "17"}))
    with pytest.raises(wt.OfficialAcquisitionError) as caught:
        api.acquire()
    err = caught.value
    assert err.kind.value == kind and err.status == status and err.retry_after.seconds == 17
    assert len(fake.calls) == 1 and err.__context__ is None and err.__cause__ is None
    assert "synthetic-password" not in repr(err) + str(err.__dict__) + caplog.text


@pytest.mark.parametrize("exception,kind", [(requests.Timeout, "timeout"), (requests.ConnectionError, "network"),
                                           (requests.RequestException, "network")])
def test_network_errors_drop_authenticated_exception(exception, kind, caplog):
    request = requests.Request("POST", wt.ENDPOINT, data={"sPassword": "synthetic-password"}).prepare()
    api, fake = client(exception("synthetic-password", request=request))
    with pytest.raises(wt.OfficialAcquisitionError) as caught:
        api.acquire()
    err = caught.value
    assert err.kind.value == kind and len(fake.calls) == 1
    assert err.__context__ is None and err.__cause__ is None
    assert not hasattr(err, "request") and not hasattr(err, "response")
    assert "synthetic-password" not in "".join(traceback.format_exception(err)) + repr(err) + caplog.text


@pytest.mark.parametrize("value", ["garbage", "-2", "", None, "synthetic-password"])
def test_invalid_retry_after_not_retained(value):
    assert wt.parse_retry_after(value) is None


def test_retry_after_date_success_and_functional_error():
    headers = {"Retry-After": "Wed, 07 Oct 2026 12:00:00 GMT"}
    api, _ = client(response(headers=headers))
    assert api.acquire().retry_after.at == datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
    api, fake = client(response(soap_fault("109"), headers=headers))
    with pytest.raises(wt.OfficialAcquisitionError) as caught:
        api.acquire()
    assert caught.value.retry_after.at.year == 2026 and len(fake.calls) == 1


@pytest.mark.parametrize("changes", [{"login": ""}, {"password": ""}, {"timezone_name": "bad-zone"},
                                    {"connect_timeout": 0}, {"read_timeout": float("nan")},
                                    {"read_timeout": float("inf")}, {"read_timeout": 121}])
def test_configuration_validation(changes):
    with pytest.raises(wt.OfficialAcquisitionError) as caught:
        wt.OfficialConfig(**{"login": "synthetic-login", "password": "synthetic-password", **changes})
    assert caught.value.kind is wt.ErrorKind.CONFIGURATION and caught.value.__context__ is None


def test_default_transport_no_cookies_netrc_or_adapter_retries(monkeypatch):
    calls = []
    def post(session, url, **kwargs):
        calls.append(url)
        assert session.trust_env is False and not session.cookies
        assert session.get_adapter(url).max_retries.total == 0
        assert kwargs["allow_redirects"] is False
        return response()
    monkeypatch.setattr(requests.Session, "post", post)
    config = wt.OfficialConfig("synthetic-login", "synthetic-password")
    assert len(wt.OfficialWideTechClient(config).acquire().records) == 1 and calls == [wt.ENDPOINT]


def test_existing_vehicle_still_uses_naive_dates_and_original_mapping():
    from gps_emi.providers.widetech import normalize_vehicle
    date = datetime(2026, 1, 2, 3, 4, 5)
    record = normalize_vehicle({"VEHID": 7, "VEH_LCNS": "SYN-MOBILE", "VEH_NAM": "SYN-PLATE", "Fecha": date})
    assert record.vehid == "7" and record.mobile_number == "SYN-MOBILE" and record.plate == "SYN-PLATE"
    assert record.gps_timestamp is date and date.tzinfo is None


@pytest.mark.parametrize("change", ["duplicate", "nested", "invalid_nil", "nil_with_text", "namespace"])
def test_invalid_optional_field_structure_is_not_silent(change):
    root = ET.fromstring(payload())
    row = root.find(f"{{{wt.DIFF}}}diffgram")[0][0]
    zones = row.find("Zones")
    if change == "duplicate":
        row.append(deepcopy(zones))
    elif change == "nested":
        ET.SubElement(zones, "unexpected")
    elif change == "invalid_nil":
        zones.set(f"{{{wt.XSI}}}nil", "maybe")
    elif change == "nil_with_text":
        zones.set(f"{{{wt.XSI}}}nil", "true")
    else:
        zones.tag = "{urn:untrusted}Zones"
    batch = wt.parse_render_excel(ET.tostring(root))
    assert batch.has_quality_issues and len(batch.records) == 1
    assert batch.records[0].zones == ()
    assert any(d.field == "Zones" for d in batch.diagnostics)


@pytest.mark.parametrize("container", ["root", "diffgram", "dataset"])
def test_nil_container_is_not_an_empty_fleet(container):
    root = ET.fromstring(payload([]))
    diff = root.find(f"{{{wt.DIFF}}}diffgram")
    node = {"root": root, "diffgram": diff, "dataset": diff[0]}[container]
    node.set(f"{{{wt.XSI}}}nil", "true")
    with pytest.raises(wt.OfficialAcquisitionError):
        wt.parse_render_excel(ET.tostring(root))


def test_parser_limits_and_internal_entity_expansion():
    for body in [b" " * (wt.MAX_XML_BYTES + 1) + b"<x/>",
                 b"<x>" * 65 + b"</x>" * 65,
                 b'<!DOCTYPE x [<!ENTITY a "expansion">]><x>&a;</x>']:
        with pytest.raises(wt.OfficialAcquisitionError) as caught:
            wt.parse_render_excel(body)
        assert caught.value.kind is wt.ErrorKind.PAYLOAD


def test_slash_date_and_finite_exponent():
    record, = wt.parse_render_excel(payload([{"FechaGPS": "2026/01/02 03:04:05", "Latitude": "1.25e-1"}])).records
    assert record.gps_timestamp.hour == 3 and record.latitude == 0.125


def test_import_does_not_load_dotenv(monkeypatch):
    import importlib.util
    import sys
    import dotenv
    def forbidden(*args, **kwargs):
        pytest.fail("Import must not read .env")
    monkeypatch.setattr(dotenv, "load_dotenv", forbidden)
    spec = importlib.util.spec_from_file_location('gps_emi.providers._import_probe', wt.__file__)
    probe = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, probe)
    spec.loader.exec_module(probe)


@pytest.mark.parametrize("codes,expected", [
    ([0, 100], "success"), ([1, 101, 106], "authentication"),
    ([6, 7, 102, 108, 116, 117], "authorization"), ([4, 5, 103], "service_unavailable"),
    ([109, 1031], "restriction"), ([110, 119, 1014], "no_data"),
    ([104, 105, 107, 111, 112, 113, 114, 115, 1003, 1004, 1007, 1008,
      1009, 1010, 1011, 1012, 1013, 1015, 1016, 1017, 1018, 1019,
      1020, 1021, 1022, 1023, 1024, 1025, 1026, 1027, 1515, 1028, 1029, 1030], "failure"),
    ([-1, 2, 999999], "unknown"),
])
def test_user_supplied_functional_code_semantics(codes, expected):
    for code in codes:
        assert wt.classify_functional_code(code).value == expected


@pytest.mark.parametrize("code", ["109", "Error 109", True, 109.0, None])
def test_code_classifier_requires_already_extracted_integer(code):
    with pytest.raises(ValueError):
        wt.classify_functional_code(code)


@pytest.mark.parametrize("code", [0, 100, 109, 110, 119, 1014])
def test_codes_in_vehicle_fields_are_data_not_functional_status(code):
    batch = wt.parse_render_excel(payload([{"Id": str(code), "Mensaje": str(code)}]))
    assert len(batch.records) == 1 and batch.records[0].gps_record_id == str(code)
    assert batch.coverage == "unknown"


def test_observed_inline_location_markup_and_json_description():
    root = ET.fromstring(payload([{"VEH_DESC": '{"ID":53,"NAME":"CAMIONETA"}'}]))
    location = root.find(f"{{{wt.DIFF}}}diffgram")[0][0].find("Localizacion")
    location.text = "Antes "
    bold = ET.SubElement(location, "B")
    bold.text = "Sitio sintético & prueba"
    bold.tail = " después"
    batch = wt.parse_render_excel(ET.tostring(root))
    record, = batch.records
    assert record.raw["Localizacion"] == "Antes <B>Sitio sintético &amp; prueba</B> después"
    assert record.classification.value == "ambulance"
    assert record.raw["VEH_DESC"] == '{"ID":53,"NAME":"CAMIONETA"}'
    assert not batch.has_quality_issues


@pytest.mark.parametrize("variant", ["script", "attribute", "nested", "nil"])
def test_unobserved_location_markup_keeps_diagnostic(variant):
    root = ET.fromstring(payload())
    location = root.find(f"{{{wt.DIFF}}}diffgram")[0][0].find("Localizacion")
    location.text = None
    bold = ET.SubElement(location, "script" if variant == "script" else "B")
    bold.text = "synthetic"
    if variant == "attribute":
        bold.set("onclick", "synthetic")
    elif variant == "nested":
        ET.SubElement(bold, "B")
    elif variant == "nil":
        location.set(f"{{{wt.XSI}}}nil", "true")
    batch = wt.parse_render_excel(ET.tostring(root))
    assert batch.records[0].raw["Localizacion"] is None
    assert any(d.code == "invalid_field_structure" and d.field == "Localizacion" for d in batch.diagnostics)


@pytest.mark.parametrize("status,kind", [(500, "http"), (200, "payload")])
def test_plain_text_error_never_guesses_authentication_or_109(status, kind, caplog):
    # Synthetic body only. The authorized manual invalid-credential request
    # returned HTTP 500 / text/plain, not a structured WideTech error envelope.
    api, fake = client(response(b"synthetic error: 101 109", status,
                                {"Content-Type": "text/plain"}))
    with pytest.raises(wt.OfficialAcquisitionError) as caught:
        api.acquire()
    assert caught.value.kind.value == kind
    assert caught.value.functional_code is None
    assert len(fake.calls) == 1
    assert "synthetic error" not in str(caught.value) + caplog.text


def functional_payload(code):
    root = ET.fromstring((FIXTURE.parent / "widetech_status_108.xml").read_bytes())
    root.find("Response/Status/code").text = code
    return ET.tostring(root)


@pytest.mark.parametrize("code,kind", [(108, "authorization"), (109, "restriction"),
    (1, "authentication"), (101, "authentication"), (103, "service_unavailable"),
    (110, "no_data"), (119, "no_data"), (1014, "no_data"), (0, "payload"),
    (100, "payload"), (999999, "functional"), (104, "functional"), (1031, "restriction")])
def test_structured_status_code_is_preserved_without_snapshot(code, kind):
    with pytest.raises(wt.OfficialAcquisitionError) as caught:
        wt.parse_render_excel(functional_payload(str(code)))
    assert caught.value.kind.value == kind
    assert caught.value.functional_code == code
    assert caught.value.functional_kind is wt.classify_functional_code(code)
    assert caught.value.retry_after is None


@pytest.mark.parametrize("filename,code,kind", [
    ("widetech_status_108.xml", 108, "authorization"),
    ("widetech_status_109_synthetic.xml", 109, "restriction")])
@pytest.mark.parametrize("retry", ["61", "Wed, 07 Oct 2026 12:00:00 GMT"])
def test_evidenced_and_synthetic_envelopes_single_call_retry_after(filename, code, kind, retry):
    api, fake = client(response((FIXTURE.parent / filename).read_bytes(), headers={"Retry-After": retry}))
    with pytest.raises(wt.OfficialAcquisitionError) as caught:
        api.acquire()
    assert caught.value.functional_code == code and caught.value.kind.value == kind
    assert caught.value.retry_after == wt.parse_retry_after(retry)
    assert len(fake.calls) == 1


@pytest.mark.parametrize("code", [None, "", "nan", "109.0", "-109", "+109", "Error 109", "١٠٩", "1" * 11])
def test_malformed_structured_code(code):
    with pytest.raises(wt.OfficialAcquisitionError) as caught:
        wt.parse_render_excel(functional_payload(code))
    assert caught.value.kind.value == "payload" and caught.value.functional_code is None


@pytest.mark.parametrize("mutation", ["missing_code", "duplicate_code", "contradictory_code",
    "duplicate_status", "contradictory_status", "duplicate_response", "duplicate_description",
    "nested_code", "namespace", "wrapper", "attribute", "extra_datatable", "text"])
def test_ambiguous_or_undefined_envelope_is_rejected(mutation):
    root = ET.fromstring(functional_payload("108"))
    response_node, = root
    status, = response_node
    code = status.find("code")
    if mutation == "missing_code":
        status.remove(code)
    elif mutation in ("duplicate_code", "contradictory_code"):
        other = deepcopy(code)
        other.text = "109" if mutation == "contradictory_code" else "108"
        status.append(other)
    elif mutation in ("duplicate_status", "contradictory_status"):
        other = deepcopy(status)
        if mutation == "contradictory_status":
            other.find("code").text = "0"
        response_node.append(other)
    elif mutation == "duplicate_response":
        root.append(deepcopy(response_node))
    elif mutation == "duplicate_description":
        status.append(deepcopy(status.find("description")))
    elif mutation == "nested_code":
        ET.SubElement(code, "nested").text = "109"
    elif mutation == "namespace":
        root.tag = "{http://shareservice.co/}space"
    elif mutation == "wrapper":
        wrapper = ET.Element("wrapper")
        wrapper.append(root)
        root = wrapper
    elif mutation == "attribute":
        code.set("value", "109")
    elif mutation == "extra_datatable":
        root.append(ET.fromstring(payload()))
    else:
        root.text = "109"
    with pytest.raises(wt.OfficialAcquisitionError) as caught:
        wt.parse_render_excel(ET.tostring(root))
    assert caught.value.kind.value == "payload" and caught.value.functional_code is None


def test_status_description_is_not_a_code_or_secret_in_error(caplog):
    root = ET.fromstring(functional_payload("108"))
    root.find("Response/Status/description").text = "synthetic-password 109 wait 20"
    api, _ = client(response(ET.tostring(root)))
    with pytest.raises(wt.OfficialAcquisitionError) as caught:
        api.acquire()
    error = caught.value
    assert error.kind.value == "authorization" and error.functional_code == 108
    assert error.retry_after is None and error.__context__ is None
    assert "synthetic-password" not in repr(error) + str(error.__dict__) + caplog.text


def test_optional_description_and_status_lookalikes_inside_vehicle():
    root = ET.fromstring(functional_payload("109"))
    status = root.find("Response/Status")
    status.remove(status.find("description"))
    with pytest.raises(wt.OfficialAcquisitionError) as caught:
        wt.parse_render_excel(ET.tostring(root))
    assert caught.value.functional_code == 109
    batch = wt.parse_render_excel(payload([{"Localizacion": "108", "Mensaje": "109", "Id": "109",
                                           "Status": "108", "code": "109"}]))
    assert len(batch.records) == 1 and not batch.has_quality_issues
