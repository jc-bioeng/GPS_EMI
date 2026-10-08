"""Isolated RenderExcel adapter. Deliberately not an operational Vehicle provider."""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
import math
import re
from types import MappingProxyType
from typing import Mapping, Protocol
import unicodedata
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from gps_emi.errors import AcquisitionError
from gps_emi.providers.widetech import zone_list


METHOD = "HistoryDataLastLocationByUserRenderExcel"
SERVICE = "https://web1ws.widetech.co/wsHistoryGetByPlate.asmx"
ENDPOINT = f"{SERVICE}/{METHOD}"
NS = "http://shareservice.co/"
XS = "http://www.w3.org/2001/XMLSchema"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
DIFF = "urn:schemas-microsoft-com:xml-diffgram-v1"
SOAP_NAMESPACES = ("http://schemas.xmlsoap.org/soap/envelope/",
                   "http://www.w3.org/2003/05/soap-envelope")
FIELDS = frozenset("Id Movil FechaGPS FechaServidor Localizacion Velocidad Rumbo MSGID "
                   "Mensaje Latitude Longitude Altitud VEH_NAM Zones StateIgnition "
                   "GPSFix fltName VEH_DESC StatusForm VEH_ID".split())
MAX_XML_BYTES = 8 * 1024 * 1024


class ErrorKind(str, Enum):
    CONFIGURATION = "configuration"
    NETWORK = "network"
    TIMEOUT = "timeout"
    HTTP = "http"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    SERVICE_UNAVAILABLE = "service_unavailable"
    NO_DATA = "no_data"
    FUNCTIONAL = "functional"
    RESTRICTION = "restriction"
    PAYLOAD = "payload"
    EMPTY = "empty_response"
    SOAP = "soap_fault"


class FunctionalCodeKind(str, Enum):
    SUCCESS = "success"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    SERVICE_UNAVAILABLE = "service_unavailable"
    RESTRICTION = "restriction"
    NO_DATA = "no_data"
    FAILURE = "failure"
    UNKNOWN = "unknown"


_FUNCTIONAL_CODES = {
    FunctionalCodeKind.SUCCESS: frozenset({0, 100}),
    FunctionalCodeKind.AUTHENTICATION: frozenset({1, 101, 106}),
    FunctionalCodeKind.AUTHORIZATION: frozenset({6, 7, 102, 108, 116, 117}),
    FunctionalCodeKind.SERVICE_UNAVAILABLE: frozenset({4, 5, 103}),
    FunctionalCodeKind.RESTRICTION: frozenset({109, 1031}),
    FunctionalCodeKind.NO_DATA: frozenset({110, 119, 1014}),
    FunctionalCodeKind.FAILURE: frozenset({
        104, 105, 107, 111, 112, 113, 114, 115, 1003, 1004, 1007, 1008,
        1009, 1010, 1011, 1012, 1013, 1015, 1016, 1017, 1018, 1019,
        1020, 1021, 1022, 1023, 1024, 1025, 1026, 1027, 1515, 1028, 1029, 1030,
    }),
}


def classify_functional_code(code: int) -> FunctionalCodeKind:
    """Classify only an extracted integer using the user's supplied code table."""
    if type(code) is not int:
        raise ValueError("Functional code must be an integer.")
    return next((kind for kind, codes in _FUNCTIONAL_CODES.items() if code in codes),
                FunctionalCodeKind.UNKNOWN)


@dataclass(frozen=True)
class RetryAfter:
    seconds: int | None = None
    at: datetime | None = None


def parse_retry_after(value: str | None) -> RetryAfter | None:
    """Keep only validated timing information, never arbitrary header text."""
    if not value:
        return None
    value = value.strip()
    if re.fullmatch(r"[0-9]{1,10}", value):
        return RetryAfter(seconds=int(value))
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is not None:
            return RetryAfter(at=date.astimezone(timezone.utc))
    except (ValueError, TypeError, OverflowError):
        pass
    return None


class OfficialAcquisitionError(AcquisitionError):
    """Safe structured failure: no response, request, provider text or cause."""
    def __init__(self, kind: ErrorKind, *, status: int | None = None,
                 retry_after: RetryAfter | None = None, functional_code: int | None = None):
        self.kind = kind
        self.status = status
        self.retry_after = retry_after
        self.functional_code = functional_code
        self.functional_kind = (classify_functional_code(functional_code)
                                if functional_code is not None else None)
        super().__init__(f"WideTech RenderExcel: {kind.value}.")


@dataclass(frozen=True)
class OfficialConfig:
    login: str = field(repr=False)
    password: str = field(repr=False)
    timezone_name: str = "America/Bogota"
    connect_timeout: float = 10.0
    read_timeout: float = 30.0

    def __post_init__(self):
        valid = (isinstance(self.login, str) and bool(self.login.strip())
                 and isinstance(self.password, str) and bool(self.password.strip()))
        valid = valid and all(type(v) in (int, float) and math.isfinite(v) and 0 < v <= 120
                              for v in (self.connect_timeout, self.read_timeout))
        try:
            ZoneInfo(self.timezone_name)
        except (ValueError, TypeError, ZoneInfoNotFoundError):
            valid = False
        if not valid:
            raise OfficialAcquisitionError(ErrorKind.CONFIGURATION)


@dataclass(frozen=True)
class Provenance:
    service: str = SERVICE
    method: str = METHOD
    classification_field: str = "fltName"


SOURCE = Provenance()


@dataclass(frozen=True)
class Diagnostic:
    code: str
    row: int | None = None  # One-based position in the diffgram, not Id.
    field: str | None = None


class FleetClass(str, Enum):
    AMBULANCE = "ambulance"
    OTHER = "other"
    UNKNOWN = "unknown"


def normalize_fleet(value: str | None) -> str | None:
    return unicodedata.normalize("NFC", value).strip() if value is not None else None


@dataclass(frozen=True, repr=False)
class OfficialRecord:
    vehicle_id: str | None
    gps_record_id: str | None
    # Immutable allowlist retains absent vs nil vs empty and the original dates/labels.
    raw: Mapping[str, str | None]
    fleet_name: str | None
    classification: FleetClass
    latitude: float | None
    longitude: float | None
    speed: float | None
    ignition: bool | None
    gps_timestamp: datetime | None
    server_timestamp: datetime | None
    zones: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]
    source: Provenance = SOURCE

    @property
    def zones_present(self) -> bool:
        return "Zones" in self.raw

    @property
    def gps_fix(self) -> str | None:
        return self.raw.get("GPSFix")


@dataclass(frozen=True, repr=False)
class AcquisitionResult:
    records: tuple[OfficialRecord, ...]
    diagnostics: tuple[Diagnostic, ...]
    duplicate_ids: tuple[str, ...]
    incomplete_rows: tuple[int, ...]
    timezone_name: str
    retry_after: RetryAfter | None = None
    source: Provenance = SOURCE
    coverage: str = field(default="unknown", init=False)

    @property
    def has_quality_issues(self) -> bool:
        return bool(self.diagnostics)


class _SafeTreeBuilder(ET.TreeBuilder):
    """Reject DTDs before entity expansion; no external fetch or XInclude processing."""
    def __init__(self):
        super().__init__()
        self.depth = 0

    def doctype(self, name, pubid, system):
        raise ValueError("DTD forbidden")

    def start(self, tag, attrs):
        self.depth += 1
        if self.depth > 64:
            raise ValueError("XML depth limit")
        return super().start(tag, attrs)

    def end(self, tag):
        self.depth -= 1
        return super().end(tag)


def _xml(payload: bytes | str):
    if not payload or not payload.strip():
        raise OfficialAcquisitionError(ErrorKind.EMPTY)
    root = None
    try:
        size = len(payload.encode("utf-8")) if isinstance(payload, str) else len(payload)
        if size <= MAX_XML_BYTES:
            root = ET.fromstring(payload, parser=ET.XMLParser(target=_SafeTreeBuilder()))
    except (ET.ParseError, ValueError, UnicodeError):
        pass
    if root is None:
        raise OfficialAcquisitionError(ErrorKind.PAYLOAD)
    return root


def _check_functional_status(root):
    """Exact unnamespaced envelope observed in GetMobileList, not RenderExcel.

    Reject ambiguity before interpreting a code. Never retain descriptions or
    infer timing from them. A status-only success is not an acquisition.
    """
    if root.tag != "space":
        return

    def container(node, child_name):
        if (node.attrib or (node.text or "").strip() or len(node) != 1
                or node[0].tag != child_name or (node[0].tail or "").strip()):
            raise OfficialAcquisitionError(ErrorKind.PAYLOAD)
        return node[0]

    status = container(container(root, "Response"), "Status")
    codes = status.findall("code")
    descriptions = status.findall("description")
    if (status.attrib or (status.text or "").strip() or len(codes) != 1
            or len(descriptions) > 1 or len(status) != len(codes) + len(descriptions)
            or any(node.attrib or len(node) or (node.tail or "").strip() for node in status)):
        raise OfficialAcquisitionError(ErrorKind.PAYLOAD)
    value = (codes[0].text or "").strip()
    if not re.fullmatch(r"[0-9]{1,10}", value):
        raise OfficialAcquisitionError(ErrorKind.PAYLOAD)
    code = int(value)
    kind = {
        FunctionalCodeKind.AUTHENTICATION: ErrorKind.AUTHENTICATION,
        FunctionalCodeKind.AUTHORIZATION: ErrorKind.AUTHORIZATION,
        FunctionalCodeKind.SERVICE_UNAVAILABLE: ErrorKind.SERVICE_UNAVAILABLE,
        FunctionalCodeKind.RESTRICTION: ErrorKind.RESTRICTION,
        FunctionalCodeKind.NO_DATA: ErrorKind.NO_DATA,
        FunctionalCodeKind.SUCCESS: ErrorKind.PAYLOAD,
    }.get(classify_functional_code(code), ErrorKind.FUNCTIONAL)
    raise OfficialAcquisitionError(kind, functional_code=code)


def _datatable(root):
    _check_functional_status(root)
    for soap in SOAP_NAMESPACES:
        if root.tag != f"{{{soap}}}Envelope":
            continue
        bodies = root.findall(f"{{{soap}}}Body")
        if len(bodies) != 1 or len(bodies[0]) != 1:
            raise OfficialAcquisitionError(ErrorKind.PAYLOAD)
        content = bodies[0][0]
        if content.tag == f"{{{soap}}}Fault":
            # The public signature does not define a WideTech functional-code
            # envelope. Do not invent a mapping from SOAP codes/prose to 109.
            raise OfficialAcquisitionError(ErrorKind.SOAP)
        if content.tag != f"{{{NS}}}{METHOD}Response" or len(content) != 1:
            raise OfficialAcquisitionError(ErrorKind.PAYLOAD)
        root = content[0]
        if root.tag != f"{{{NS}}}{METHOD}Result":
            raise OfficialAcquisitionError(ErrorKind.PAYLOAD)
        break
    else:
        if root.tag != f"{{{NS}}}DataTable":
            raise OfficialAcquisitionError(ErrorKind.PAYLOAD)
    if (root.get(f"{{{XSI}}}nil") in ("true", "1")
            or (root.text or "").strip()
            or len(root) != 2 or len(root.findall(f"{{{XS}}}schema")) != 1
            or len(root.findall(f"{{{DIFF}}}diffgram")) != 1):
        raise OfficialAcquisitionError(ErrorKind.PAYLOAD)
    diff = root.find(f"{{{DIFF}}}diffgram")
    if (diff.text or "").strip() or diff.get(f"{{{XSI}}}nil") in ("true", "1"):
        raise OfficialAcquisitionError(ErrorKind.PAYLOAD)
    if not len(diff):
        return []
    if len(diff) != 1 or diff[0].tag != "NewDataSet":
        raise OfficialAcquisitionError(ErrorKind.PAYLOAD)
    if (diff[0].text or "").strip() or diff[0].get(f"{{{XSI}}}nil") in ("true", "1"):
        raise OfficialAcquisitionError(ErrorKind.PAYLOAD)
    if any(row.tag != "Table" for row in diff[0]):
        raise OfficialAcquisitionError(ErrorKind.PAYLOAD)
    return list(diff[0])


def _record(element, index, zone):
    raw, issues = {}, []

    def issue(code, name):
        issues.append(Diagnostic(code, index, name))

    if element.get(f"{{{XSI}}}nil") in ("true", "1") or (element.text or "").strip():
        issue("invalid_field_structure", "Table")
    for child in element:
        name = child.tag
        if name not in FIELDS:
            local_name = name.rsplit("}", 1)[-1]
            if local_name in FIELDS:
                issue("unexpected_field_namespace", local_name)
            continue
        if name in raw:
            issue("duplicate_field", name)
            raw[name] = None
            continue
        nil = child.get(f"{{{XSI}}}nil", "false")
        inline_location = (name == "Localizacion" and len(child) > 0
                           and all(node.tag == "B" and not node.attrib and not len(node)
                                   for node in child))
        if (len(child) and not inline_location) or nil not in ("true", "1", "false", "0") or (
                nil in ("true", "1") and (child.text not in (None, "") or len(child))):
            issue("invalid_field_structure", name)
            raw[name] = None
        elif inline_location:
            raw[name] = (child.text or "") + "".join(
                ET.tostring(node, encoding="unicode") for node in child)
        else:
            raw[name] = None if nil in ("true", "1") else (child.text or "")

    def text(name):
        value = raw.get(name)
        return value.strip() if value is not None else None

    def number(name):
        value = text(name)
        if not value:
            return None
        try:
            result = float(value)
            if (math.isfinite(result) and
                    re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value)):
                return result
        except ValueError:
            pass
        issue("invalid_number", name)
        return None

    def timestamp(name):
        value = text(name)
        if not value:
            return None
        parsed = None
        try:
            # Date-only and locale-dependent dates are intentionally unsupported.
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?", value):
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            elif re.fullmatch(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}", value):
                parsed = datetime.strptime(value, "%Y/%m/%d %H:%M:%S")
        except ValueError:
            pass
        if parsed is None:
            issue("invalid_timestamp", name)
            return None
        try:
            if parsed.tzinfo is not None:
                return parsed.astimezone(zone)
            aware = parsed.replace(tzinfo=zone)
            if (aware.utcoffset() != parsed.replace(tzinfo=zone, fold=1).utcoffset()
                    or aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != parsed):
                issue("ambiguous_or_nonexistent_timestamp", name)
                return None
            return aware
        except (OverflowError, ValueError):
            issue("invalid_timestamp", name)
            return None

    fleet = normalize_fleet(raw.get("fltName"))
    classification = (FleetClass.UNKNOWN if not fleet else
                      FleetClass.AMBULANCE if fleet.startswith("Ambulancias") else FleetClass.OTHER)
    ignition_raw = text("StateIgnition")
    ignition = {"0": False, "1": True, "false": False, "true": True}.get(ignition_raw)
    if ignition_raw and ignition is None:
        issue("invalid_ignition", "StateIgnition")
    latitude, longitude, speed = number("Latitude"), number("Longitude"), number("Velocidad")
    gps, server = timestamp("FechaGPS"), timestamp("FechaServidor")
    required = {"VEH_ID": text("VEH_ID"), "Id": text("Id"), "FechaGPS": gps,
                "Latitude": latitude, "Longitude": longitude, "fltName": fleet}
    for name, value in required.items():
        if value is None or value == "":
            issue("incomplete_record", name)
    return OfficialRecord(text("VEH_ID") or None, text("Id") or None,
                          MappingProxyType(raw), fleet, classification, latitude, longitude,
                          speed, ignition, gps, server, tuple(zone_list(raw.get("Zones"))), tuple(issues))


def parse_render_excel(payload: bytes | str, *, timezone_name="America/Bogota",
                       retry_after: RetryAfter | None = None) -> AcquisitionResult:
    zone = None
    try:
        zone = ZoneInfo(timezone_name)
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        pass
    if zone is None:
        raise OfficialAcquisitionError(ErrorKind.CONFIGURATION)
    rows = _datatable(_xml(payload))
    records = tuple(_record(row, i, zone) for i, row in enumerate(rows, 1))
    counts = Counter(record.vehicle_id for record in records if record.vehicle_id is not None)
    duplicates = tuple(key for key, count in counts.items() if count > 1)
    diagnostics = [d for record in records for d in record.diagnostics]
    diagnostics.extend(Diagnostic("duplicate_identity", i, "VEH_ID")
                       for i, record in enumerate(records, 1) if record.vehicle_id in duplicates)
    incomplete = tuple(i for i, record in enumerate(records, 1)
                       if any(d.code == "incomplete_record" for d in record.diagnostics))
    return AcquisitionResult(records, tuple(diagnostics), duplicates, incomplete,
                             timezone_name, retry_after)


class HTTPTransport(Protocol):
    def post(self, url: str, **kwargs) -> requests.Response: ...


class RequestsTransport:
    """A fresh session per call: no cookies, netrc, redirects or retry adapters."""
    def post(self, url: str, **kwargs) -> requests.Response:
        with requests.Session() as session:
            session.trust_env = False
            session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
            return session.post(url, **kwargs)


class OfficialWideTechClient:
    def __init__(self, config: OfficialConfig, *, transport: HTTPTransport | None = None):
        self.config = config
        self.transport = transport if transport is not None else RequestsTransport()

    def acquire(self) -> AcquisitionResult:
        error = None
        payload = None
        retry_after = None
        try:
            response = self.transport.post(
                ENDPOINT, data={"sLogin": self.config.login, "sPassword": self.config.password},
                headers={"Accept": "application/xml", "Content-Type": "application/x-www-form-urlencoded"},
                timeout=(self.config.connect_timeout, self.config.read_timeout), allow_redirects=False)
            with response:
                status = response.status_code
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                if status != 200:
                    kind = (ErrorKind.AUTHENTICATION if status in (401, 403) else
                            ErrorKind.RESTRICTION if status == 429 else ErrorKind.HTTP)
                    error = OfficialAcquisitionError(kind, status=status, retry_after=retry_after)
                else:
                    payload = response.content
        except requests.Timeout:
            error = OfficialAcquisitionError(ErrorKind.TIMEOUT)
        except requests.RequestException:
            error = OfficialAcquisitionError(ErrorKind.NETWORK)
        # Raise outside except: never chain an exception retaining authenticated requests.
        if error is not None:
            raise error
        try:
            return parse_render_excel(payload, timezone_name=self.config.timezone_name,
                                      retry_after=retry_after)
        except OfficialAcquisitionError as failure:
            failure.retry_after = retry_after
            raise
