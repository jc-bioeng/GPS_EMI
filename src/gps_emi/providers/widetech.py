"""Consulta experimental de LoadDataLog de GPSpace/WideTech.

Configura GPSPACE_COOKIE localmente. No pegues cookies en este archivo.
El endpoint es interno/no documentado y puede cambiar.
"""
import os
import re
from datetime import datetime
import requests

from gps_emi.models import Vehicle, normalize_plate

URL = "https://gpspace.app/EMI/ajax/Widetech.WEB.OnLine,Widetech.ashx"
PARAMETERS = "REMOVED_HISTORICAL_SESSION_MATERIAL"
TARGET_FLEET = "Ambulancias Medellin;44986;0"

FIELDS = (
    "VEHID", "VEH_LCNS", "VEH_NAM", "Fecha", "FechaInsert",
    "Longitude", "Latitude", "Location", "Velocidad", "Rumbo", "GPSFix",
    "MSG", "Heading", "StateIgnition", "Zones", "fltName2",
    "vehDateTimeUTC", "vehDBServer", "LastUpdate", "fltName"
)


class WideTechError(RuntimeError):
    """Error seguro: nunca incluye cuerpos, cookies ni excepciones HTTP."""


class WideTechClient:
    """Adaptador del endpoint interno observado, sin contrato oficial.

    Parameters y formato HTTP se conservan del prototipo validado.
    get_vehicles devuelve exclusivamente Ambulancias Medellín.
    """

    def load_data_log(self):
        cookie = os.getenv("GPSPACE_COOKIE", "").strip()
        if not cookie:
            raise WideTechError("Falta la variable de entorno GPSPACE_COOKIE.")
        headers = {
            "Accept": "*/*",
            "Content-Type": os.getenv("GPSPACE_CONTENT_TYPE", "text/plain;charset=UTF-8"),
            "Referer": "https://gpspace.app/EMI/Site/OnLine.aspx",
            "User-Agent": "Mozilla/5.0",
            "Cookie": cookie,
        }
        error_message = None
        try:
            response = requests.post(
                URL, params={"_method": "LoadDataLog", "_session": "rw"},
                headers=headers, data=("Parameters=" + PARAMETERS).encode("utf-8"),
                timeout=60, allow_redirects=False,
            )
            with response:
                if response.status_code in (401, 403) or 300 <= response.status_code < 400:
                    error_message = (
                        "La sesión de GPSpace no es válida o expiró. "
                        "Inicie sesión en GPSpace y actualice GPSPACE_COOKIE."
                    )
                elif response.status_code != 200:
                    error_message = (
                        "WideTech no respondió correctamente "
                        f"(HTTP {response.status_code}). Inténtelo de nuevo."
                    )
                else:
                    payload = response.text
        except requests.RequestException:
            error_message = (
                "No se pudo conectar con GPSpace. Revise la conexión a Internet e inténtelo de nuevo."
            )
        # Fuera del except para no conservar una excepción con petición autenticada.
        if error_message:
            raise WideTechError(error_message)
        return payload

    def get_vehicles(self) -> list[Vehicle]:
        payload = self.load_data_log()
        if not re.search(r"['\"]Rows['\"]\s*:\s*\[", payload):
            raise WideTechError(
                "GPSpace no devolvió datos de vehículos. La sesión puede haber expirado: "
                "inicie sesión en GPSpace y actualice GPSPACE_COOKIE."
            )
        failed = False
        try:
            rows = parse(payload)
            vehicles = [normalize_vehicle(row) for row in rows
                        if row.get("fltName") == TARGET_FLEET]
        except (ValueError, TypeError, OverflowError):
            failed = True
        if failed:
            raise WideTechError("Respuesta WideTech no reconocida. Revise sesión o formato del proveedor.")
        return vehicles


def load_data_log():
    """Compatibilidad con el prototipo."""
    return WideTechClient().load_data_log()


def split_rows(text):
    m = re.search(r"['\"]Rows['\"]\s*:\s*\[", text)
    if not m:
        raise ValueError("No se encontro Rows.")

    rows, depth, start = [], 0, None
    quote, escaped = None, False
    i = m.end()

    while i < len(text):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        else:
            if ch in ("'", '"'):
                quote = ch
            elif ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    rows.append(text[start:i+1])
                    start = None
            elif ch == "]" and depth == 0:
                return rows
        i += 1
    raise ValueError("Rows incompleto.")


def extract(row, field):
    key = re.escape(field)
    pattern = (
        r"[\"']" + key + r"[\"']\s*:\s*("
        r"new Date\([^)]*\)|null|true|false|-?\d+(?:\.\d+)?"
        r"|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\""
        r")"
    )
    m = next((match for part in top_level_fields(row)
              if (match := re.fullmatch(pattern, part.strip(), re.S))), None)
    if not m:
        return None
    raw = m.group(1).strip()

    if raw.startswith("new Date("):
        nums = list(map(int, re.findall(r"\d+", raw)))
        if len(nums) == 6:
            y, month0, d, h, minute, s = nums
            return datetime(y, month0 + 1, d, h, minute, s)

    if raw == "null":
        return None
    if raw in ("true", "false"):
        return raw == "true"
    if raw[:1] in ("'", '"'):
        return raw[1:-1].replace("\\'", "'").replace('\\\"', '"')

    try:
        return float(raw) if "." in raw else int(raw)
    except ValueError:
        return raw


def parse(text):
    result = []
    for raw in split_rows(text):
        item = {f: extract(raw, f) for f in FIELDS}
        for c in ("Latitude", "Longitude"):
            try:
                item[c] = float(item[c]) if item[c] not in (None, "") else None
            except (TypeError, ValueError):
                pass
        result.append(item)
    return result


def zone_list(value):
    return re.findall(r"\{([^{}]+)\}", value or "")



def normalize_vehicle(row):
    timestamp = row.get("Fecha")
    speed = row.get("Velocidad")
    return Vehicle(
        vehid=str(row.get("VEHID") or ""),
        plate=normalize_plate(str(row.get("VEH_LCNS") or "")),
        mobile_name=str(row.get("VEH_NAM") or "").strip(),
        gps_timestamp=timestamp if isinstance(timestamp, datetime) else None,
        location=row.get("Location"),
        speed=float(speed) if speed not in (None, "") else None,
        ignition=row.get("StateIgnition"), gps_fix=row.get("GPSFix"),
        zones=zone_list(row.get("Zones")),
    )


def top_level_fields(row):
    """Separa campos sin interpretar JS ni confundir claves dentro de Sensors."""
    depth, start = 0, 1
    quote, escaped = None, False
    for i in range(1, len(row) - 1):
        ch = row[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        elif ch in ("'", '\"'):
            quote = ch
        elif ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        elif ch == "," and depth == 0:
            yield row[start:i]
            start = i + 1
    yield row[start:-1]
