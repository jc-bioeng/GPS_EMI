"""Consulta experimental de LoadDataLog de GPSpace/WideTech.

Configura GPSPACE_COOKIE localmente. No pegues cookies en este archivo.
El endpoint es interno/no documentado y puede cambiar.
"""
import os
import re
import sys
from datetime import datetime
import requests

URL = "https://gpspace.app/EMI/ajax/Widetech.WEB.OnLine,Widetech.ashx"
PARAMETERS = "REMOVED_HISTORICAL_SESSION_MATERIAL"
TARGET_FLEET = "Ambulancias Medellin;44986;0"

FIELDS = (
    "VEHID", "VEH_LCNS", "VEH_NAM", "Fecha", "FechaInsert",
    "Longitude", "Latitude", "Location", "Velocidad", "Rumbo", "GPSFix",
    "MSG", "Heading", "StateIgnition", "Zones", "fltName2",
    "vehDateTimeUTC", "vehDBServer", "LastUpdate", "fltName"
)


def load_data_log():
    cookie = os.getenv("GPSPACE_COOKIE", "").strip()
    if not cookie:
        raise RuntimeError("Falta la variable de entorno GPSPACE_COOKIE.")

    headers = {
        "Accept": "*/*",
        "Content-Type": os.getenv(
            "GPSPACE_CONTENT_TYPE", "text/plain;charset=UTF-8"
        ),
        "Referer": "https://gpspace.app/EMI/Site/OnLine.aspx",
        "User-Agent": "Mozilla/5.0",
        "Cookie": cookie,
    }
    params = {"_method": "LoadDataLog", "_session": "rw"}
    r = requests.post(
        URL, params=params, headers=headers,
        data=("Parameters=" + PARAMETERS).encode("utf-8"), timeout=60
    )
    r.raise_for_status()
    if not re.search(r"['\"]Rows['\"]\s*:", r.text):
        raise RuntimeError(
            "La respuesta no contiene Rows. La sesion puede haber expirado "
            "o el Content-Type puede diferir del observado."
        )
    return r.text


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
                break
        i += 1
    return rows


def extract(row, field):
    key = re.escape(field)
    pattern = (
        r"'" + key + r"'\s*:\s*("
        r"new Date\([^)]*\)|null|true|false|-?\d+(?:\.\d+)?"
        r"|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\""
        r")"
    )
    m = re.search(pattern, row, re.S)
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


def main():
    rows = parse(load_data_log())
    medellin = [r for r in rows if r.get("fltName") == TARGET_FLEET]

    print("Registros totales:", len(rows))
    print("Ambulancias Medellin:", len(medellin))
    print("-" * 90)

    for r in medellin:
        print(
            f"{r.get('VEH_LCNS') or r.get('VEH_NAM')} | "
            f"VEHID={r.get('VEHID')} | "
            f"GPS={r.get('Fecha')} | "
            f"lat={r.get('Latitude')} lon={r.get('Longitude')} | "
            f"speed={r.get('Velocidad')} | "
            f"fix={r.get('GPSFix')} ign={r.get('StateIgnition')}"
        )
        print(" Location:", r.get("Location"))
        print(" Zones:   ", zone_list(r.get("Zones")))
        print()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(1)
