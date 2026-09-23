"""Presentación WhatsApp de resultados I3, sin lógica GPS."""
from gps_emi.formatting import format_age, format_speed, format_ignition
from gps_emi.monitoring.observation import gps_fix_warning
from gps_emi.sites import EMI_SITES

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
VIGILANCIAS
MISVIGILANCIAS
DETENER
MENU

Puedes utilizar placa o número de móvil. MENU reinicia la conversación;
no cancela una vigilancia activa. Para soporte, contacta al responsable de Biomédica."""
SITE_PROMPT = "🏥 Ambulancias en sede\n\nSelecciona una sede:\n1️⃣ EMI Medellin_Poblado\n2️⃣ EMI_Medellin_Taller"
DENIED = "🔒 Este número no está autorizado para consultar información del sistema GPS EMI."
GPS_ERROR = "⚠️ No fue posible consultar GPS EMI en este momento.\nEl acceso a GPSpace requiere atención del sistema."
NO_WATCHES = "🚑 No tienes vigilancias activas."


def watch_identity(watch):
    return f"{display(watch.mobile_number)} · {display(watch.plate)}"


def format_watch_started(watch):
    sites = watch.monitor.actual_sites
    if sites:
        location = site_name(sites[0]) if len(sites) == 1 else (
            "ambas sedes EMI: " + " / ".join(site_name(site) for site in sites)
            + " (sin sede única)"
        )
        return ("👀 Vigilancia iniciada\n\n"
                + f"La última posición reportada de {watch_identity(watch)} corresponde a {location}."
                + "\n\nLa vigilancia seguirá activa para detectar una próxima llegada después de observar una salida."
                + "\nSi no necesitas esperar otra llegada, puedes detener esta vigilancia con la opción siguiente o escribir DETENER."
                + "\nEscribe VIGILANCIAS para gestionar tus vigilancias.")
    return ("👀 Vigilancia iniciada\n\n" + watch_identity(watch)
            + "\n\nTe avisaré cuando llegue a una sede EMI.\nEscribe VIGILANCIAS para gestionar tus vigilancias.")


def format_watch_duplicate(watch):
    return f"🚑 {watch_identity(watch)} ya tiene una vigilancia activa."


def format_watch_cancelled(watch):
    return "⏹️ Vigilancia detenida\n\n" + watch_identity(watch)


def format_watch_failed(watch):
    return ("⚠️ Vigilancia detenida\n\n" + watch_identity(watch)
            + "\n\nNo fue posible continuar consultando GPS EMI. El acceso requiere atención del sistema."
            + "\nCuando se restablezca, solicita nuevamente la vigilancia.")


def format_watches(watches, cancelling=False):
    if not watches:
        return NO_WATCHES
    title = "⏹️ Detener vigilancia" if cancelling else "🚑 Vigilancias activas"
    lines = [title, ""]
    for number, watch in enumerate(watches, 1):
        lines.append(f"{number}. {watch_identity(watch)}\n   Vigilando\n")
    lines.append("Responde con el número de la vigilancia que deseas detener." if cancelling
                 else "VIGILAR: nueva · DETENER: detener una · MENU: inicio")
    return "\n".join(lines)


def display(value):
    return str(value) if value is not None and str(value).strip() else "N/D"


def identifier_prompt(watch=False):
    title = "🔔 Vigilar llegada" if watch else "📍 Consultar ubicación"
    return title + "\n\nEscribe la placa o número de móvil.\nEjemplos:\n• AMB-20\n• PJU886"


def identity(vehicle):
    return f"🚑 Móvil: {display(vehicle.mobile_number)}\n🔖 Placa: {display(vehicle.plate)}"


def site_name(site):
    return dict(zip(EMI_SITES, ("EMI Medellín - Poblado", "EMI Medellín - Taller"))).get(site, site)


def freshness(result):
    icon = "⚠️" if result.stale else "🟢" if result.stale is False and result.report_age is not None and result.report_age >= 0 else "❔"
    age = format_age(result.report_age)
    return f"{icon} {age[:1].upper() + age[1:]}"


def format_location(result):
    vehicle = result.vehicle
    lines = ["📍 Última posición reportada", "", identity(vehicle), "", display(vehicle.location), "",
             f"Hora GPS: {display(vehicle.gps_timestamp)}", freshness(result),
             f"🚗 {format_speed(result)}", f"🔑 Ignición: {format_ignition(vehicle.ignition)}",
             f"📡 GPSFix: {display(vehicle.gps_fix)}"]
    if gps_fix_warning(vehicle.gps_fix):
        lines.append("⚠️ GPSFix=0: advertencia diagnóstica; posición conservada.")
    lines.append("\nEsta es la última posición reportada y no garantiza la ubicación física actual.")
    return "\n".join(lines)


def format_site(result):
    lines = [f"🏥 Ambulancias en {site_name(result.site)}"]
    if not result.entries:
        lines.append("\nNo hay ambulancias cuya última posición reportada pertenezca a esta sede.")
    else:
        lines.extend([f"{len(result.entries)} ambulancias reportadas", ""])
        for entry in result.entries:
            vehicle = entry.vehicle
            movement = entry.movement.value if entry.movement else "Movimiento N/D"
            lines.extend([f"{display(vehicle.mobile_number)} · {display(vehicle.plate)}",
                          f"{freshness(entry)} · {movement} · GPSFix: {display(vehicle.gps_fix)}", ""])
        # lines.append("⚠️ Reporte desactualizado. ❔ Antigüedad no disponible o reloj por revisar.")
    lines.append("_Basado en la última posición reportada; no garantiza presencia física actual._")
    return "\n".join(lines)


def format_started(vehicle):
    return "🔔 Vigilancia iniciada\n\n" + identity(vehicle) + "\n\nTe avisaré cuando se detecte su llegada a EMI."


def format_arrival(event):
    site = event.site or ("Sedes reportadas simultáneamente (sin sede única): " + " / ".join(event.sites))
    return ("🚑 Llegada de ambulancia detectada\n\n" + identity(event.vehicle)
            + f"\n{site}\nHora GPS: {display(event.vehicle.gps_timestamp)}"
            + "\nLa vigilancia ha finalizado."
            + "\nBasado en la última posición reportada; no garantiza ubicación física actual.")
