"""Presentación WhatsApp de resultados I3, sin lógica GPS."""
from gps_emi.formatting import format_age, format_speed, format_ignition
from gps_emi.monitoring.observation import gps_fix_warning

MENU = """🚑 GPS EMI — Biomédica

¿Qué deseas hacer?

1️⃣ Vigilar llegada de ambulancia
2️⃣ Consultar ubicación
3️⃣ Ver ambulancias en sede
4️⃣ Ayuda

También puedes escribir un comando directamente."""
HELP = """ℹ️ GPS EMI — Ayuda

1️⃣ Vigilar llegada
Recibe una notificación cuando se detecte una llegada a EMI.
2️⃣ Consultar ubicación
Consulta la última posición reportada por GPS.
3️⃣ Ver ambulancias en sede
Consulta los móviles cuya última posición corresponde a Poblado o Taller.

Comandos rápidos:
VIGILAR AMB-20
UBICACION AMB-20
SEDE POBLADO
SEDE TALLER
MENU

Puedes utilizar placa o número de móvil. MENU reinicia la conversación;
no cancela una vigilancia activa. Para soporte, contacta al responsable de Biomédica."""
SITE_PROMPT = "🏥 Ambulancias en sede\n\nSelecciona una sede:\n1️⃣ EMI Medellin_Poblado\n2️⃣ EMI_Medellin_Taller"
DENIED = "🔒 Este número no está autorizado para consultar información del sistema GPS EMI."
GPS_ERROR = "⚠️ No fue posible consultar GPS EMI en este momento.\nEl acceso a GPSpace requiere atención del sistema."
BUSY = "⚠️ Ya existe una vigilancia activa en el piloto. Espera a que finalice."


def display(value):
    return str(value) if value is not None and str(value).strip() else "N/D"


def identifier_prompt(watch=False):
    title = "🔔 Vigilar llegada" if watch else "📍 Consultar ubicación"
    return title + "\n\nEscribe la placa o número de móvil.\nEjemplos:\n• AMB-20\n• PJU886"


def identity(vehicle):
    return f"🚑 Móvil: {display(vehicle.mobile_number)}\n🔖 Placa: {display(vehicle.plate)}"


def format_location(result):
    vehicle = result.vehicle
    age = format_age(result.report_age)
    freshness = f"⚠️ STALE — Reporte desactualizado — {age}" if result.stale else f"🕐 {age}"
    lines = ["📍 Última posición reportada", "", identity(vehicle), "", display(vehicle.location), "",
             f"Hora GPS: {display(vehicle.gps_timestamp)}", freshness,
             f"🚗 {format_speed(result)}", f"🔑 Ignición: {format_ignition(vehicle.ignition)}",
             f"📡 GPSFix: {display(vehicle.gps_fix)}"]
    if gps_fix_warning(vehicle.gps_fix):
        lines.append("⚠️ GPSFix=0: advertencia diagnóstica; posición conservada.")
    lines.append("\nEsta es la última posición reportada y no garantiza la ubicación física actual.")
    return "\n".join(lines)


def format_site(result):
    lines = [f"🏥 {result.site}"]
    if not result.entries:
        lines.append("\nNo hay ambulancias cuya última posición reportada pertenezca a esta sede.")
    else:
        lines.extend([f"{len(result.entries)} ambulancias reportadas", ""])
        for entry in result.entries:
            icon = "⚠️ STALE" if entry.stale else "🟢" if entry.stale is False and entry.report_age >= 0 else "❔"
            vehicle = entry.vehicle
            lines.append(f"{icon} {display(vehicle.mobile_number)} | {display(vehicle.plate)} — {format_age(entry.report_age)}")
        lines.append("\n⚠️ STALE = reporte desactualizado. ❔ = antigüedad no disponible o reloj por revisar.")
    lines.append("Basado en la última posición reportada; no garantiza presencia física actual.")
    return "\n".join(lines)


def format_started(vehicle):
    return "🔔 Vigilancia iniciada\n\n" + identity(vehicle) + "\n\nTe avisaré cuando se detecte su llegada a EMI."


def format_arrival(event):
    site = event.site or ("Sedes reportadas simultáneamente (sin sede única): " + " / ".join(event.sites))
    return ("🚑 Llegada de ambulancia detectada\n\n" + identity(event.vehicle)
            + f"\n{site}\nHora GPS: {display(event.vehicle.gps_timestamp)}"
            + "\nBasado en la última posición reportada; no garantiza ubicación física actual.")
