"""Presentación determinista de resultados; no consulta al proveedor."""
import math

from gps_emi.monitoring.observation import gps_fix_warning
from gps_emi.queries import LocationResult, SiteResult


def format_age(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds):
        return "N/D"
    if seconds < 0:
        return "fecha futura (revisar reloj)"
    if seconds < 60:
        return f"hace {int(seconds)} s"
    if seconds < 3600:
        return f"hace {int(seconds // 60)} min"
    return f"hace {int(seconds // 3600)} h"


def _display(value) -> str:
    return "N/D" if value is None or str(value).strip() == "" else str(value)


def acquisition_note(result):
    info = result.acquisition
    if info is None:
        return ''
    prefix = 'Dato conservado; ' if info.retained else ''
    return prefix + f"Última adquisición: {info.acquired_at.isoformat()} ({format_age(info.age_seconds)})."


def format_speed(result: LocationResult) -> str:
    speed = result.vehicle.speed
    if not isinstance(speed, (float, int)) or not math.isfinite(speed):
        return "N/D"
    movement = result.movement.value if result.movement is not None else "N/D"
    return f"{speed:g} km/h — {movement}"


def format_ignition(value) -> str:
    if value in (1, "1"):
        return "Encendida"
    if value in (0, "0"):
        return "Apagada"
    return "N/D"


def format_location(result: LocationResult) -> str:
    vehicle = result.vehicle
    status = "STALE" if result.stale else "Sin alerta de antigüedad" if result.stale is False else "N/D"
    if result.report_age is not None and result.report_age < 0:
        status = "Fecha futura: revisar reloj"
    lines = [
        f"Número de móvil: {_display(vehicle.mobile_number)}",
        f"Placa: {_display(vehicle.plate)}",
        "Última posición reportada:",
        _display(vehicle.location),
        f"Hora GPS: {_display(vehicle.gps_timestamp)}",
        f"Antigüedad del reporte: {format_age(result.report_age)}",
        f"Estado del reporte: {status}",
        f"Velocidad: {format_speed(result)}",
        f"Ignición: {format_ignition(vehicle.ignition)}",
        f"GPSFix: {_display(vehicle.gps_fix)}",
    ]
    if gps_fix_warning(vehicle.gps_fix):
        lines.append("ADVERTENCIA: GPSFix=0; se conserva la última posición reportada.")
    if result.acquisition is not None:
        lines.append(acquisition_note(result))
    return "\n".join(lines)


def format_site_inventory(result: SiteResult) -> str:
    lines = [result.site,
             "Ambulancias cuya última posición reportada pertenece a esta geocerca.",
             "La lista no garantiza presencia física actual; los reportes STALE se conservan."]
    if result.acquisition is not None:
        lines.append(acquisition_note(result))
    if not result.entries:
        return "\n".join(lines + ["No hay ambulancias reportadas en esta sede."])
    rows = [("Móvil", "Placa", "Velocidad / movimiento", "Último reporte", "GPSFix")]
    for entry in result.entries:
        vehicle = entry.vehicle
        age = ("STALE — " if entry.stale else "") + format_age(entry.report_age)
        if entry.acquisition is not None and entry.acquisition.retained:
            age += ' — ' + acquisition_note(entry)
        fix = "0 (advertencia)" if gps_fix_warning(vehicle.gps_fix) else _display(vehicle.gps_fix)
        rows.append((_display(vehicle.mobile_number), _display(vehicle.plate),
                     format_speed(entry), age, fix))
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    for index, row in enumerate(rows):
        lines.append(" | ".join(value.ljust(width) for value, width in zip(row, widths)))
        if index == 0:
            lines.append("-+-".join("-" * width for width in widths))
    return "\n".join(lines)
