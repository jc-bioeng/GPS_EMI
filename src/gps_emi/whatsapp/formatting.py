"""Presentación WhatsApp de resultados I3, sin lógica GPS."""
from html.parser import HTMLParser

from gps_emi.formatting import format_age, format_speed, format_ignition, acquisition_note
from gps_emi.monitoring.observation import gps_fix_warning
from gps_emi.sites import EMI_SITES

MENU = """🚑 GPS EMI — Biomédica

¿Qué deseas hacer?

1️⃣ Vigilar llegada de ambulancia
2️⃣ Consultar ubicación
3️⃣ Ver ambulancias en sede
4️⃣ Ayuda
5️⃣ Gestionar vigilancias

_Responde con el número de una opción. También puedes escribir un comando directamente._"""
HELP = """ℹ️ GPS EMI — Ayuda

1️⃣ Vigilar llegada
_Recibe una notificación cuando se detecte una llegada a EMI._
2️⃣ Consultar ubicación
_Consulta la última posición reportada por GPS._
3️⃣ Ver ambulancias en sede
_Consulta los móviles cuya última posición corresponde a Poblado o Taller._

Comandos rápidos:
VIGILAR AMB-20
UBICACION AMB-20
SEDE POBLADO
SEDE TALLER
VIGILANCIAS
MISVIGILANCIAS
DETENER
MENU

_Puedes utilizar placa o número de móvil. MENU reinicia la conversación; no cancela una vigilancia activa. Para soporte, contacta al responsable de Biomédica._"""
WATCH_MENU = """🚑 Vigilancias

1. Nueva vigilancia
2. Mis vigilancias
3. Detener vigilancia
4. Menú principal

_Responde con el número de una opción._"""
SITE_PROMPT = "🏥 Ambulancias en sede\n\n1. EMI Medellín - Poblado\n2. EMI Medellín - Taller\n\n_Responde con el número de una sede._"
DENIED = "🔒 Este número no está autorizado para consultar información del sistema GPS EMI."
GPS_ERROR = "⚠️ Nuestra adquisición GPS no está disponible en este momento. Intenta la consulta nuevamente."
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
                + "\n\n_La vigilancia seguirá activa para detectar una próxima llegada después de observar una salida._"
                + "\n_Puedes detener esta vigilancia escribiendo DETENER._"
                + "\n_Escribe VIGILANCIAS para gestionar tus vigilancias._")
    return ("👀 Vigilancia iniciada\n\n" + watch_identity(watch)
            + "\n\n_Te avisaré cuando llegue a una sede EMI._\n_Escribe VIGILANCIAS para gestionar tus vigilancias._")


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
    lines.append("_Responde con el número de la vigilancia que deseas detener._" if cancelling
                 else "_VIGILAR: nueva · DETENER: detener una · MENU: inicio_")
    return "\n".join(lines)


def display(value):
    return str(value) if value is not None and str(value).strip() else "N/D"


class _LocationText(HTMLParser):
    """Extrae texto visible sin ejecutar ni conservar markup del proveedor."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = None

    def handle_starttag(self, tag, attrs):
        if self.hidden:
            return
        if tag in {"script", "style"}:
            self.hidden = tag
        elif tag in {"br", "p", "div", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden:
                self.hidden = None
        elif tag in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def display_location(value):
    """Limpia únicamente la presentación; Vehicle.location conserva el original."""
    if value is None:
        return "N/D"
    parser = _LocationText()
    parser.feed(str(value))
    parser.close()
    return display("".join(parser.parts).strip())


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
    lines = ["📍 Última posición reportada", "", identity(vehicle), "", display_location(vehicle.location), "",
             f"Hora GPS: {display(vehicle.gps_timestamp)}", freshness(result),
             f"🚗 {format_speed(result)}", f"🔑 Ignición: {format_ignition(vehicle.ignition)}",
             f"📡 GPSFix: {display(vehicle.gps_fix)}"]
    if gps_fix_warning(vehicle.gps_fix):
        lines.append("⚠️ GPSFix=0: advertencia diagnóstica; posición conservada.")
    lines.append("\n_Esta es la última posición reportada y no garantiza la ubicación física actual._")
    if result.acquisition is not None:
        lines.append(acquisition_note(result))
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
            if entry.acquisition is not None and entry.acquisition.retained:
                lines.append(acquisition_note(entry))
        # lines.append("⚠️ Reporte desactualizado. ❔ Antigüedad no disponible o reloj por revisar.")
    lines.append("_Basado en la última posición reportada; no garantiza presencia física actual._")
    if result.acquisition is not None:
        lines.append(acquisition_note(result))
    return "\n".join(lines)


def format_started(vehicle):
    return "🔔 Vigilancia iniciada\n\n" + identity(vehicle) + "\n\nTe avisaré cuando se detecte su llegada a EMI."


def format_arrival(event):
    if event.event_type == 'PRESENCE_CONFIRMED':
        return ("🚑 Presencia confirmada tras interrupción\n\n" + identity(event.vehicle)
                + f"\n{event.destination}\nHora del reporte GPS: {display(event.vehicle.gps_timestamp)}"
                + "\nNo se conoce la hora de llegada. La vigilancia ha finalizado."
                + "\nBasado en posiciones reportadas; no garantiza ubicación física actual.")
    site = event.site or ("Sedes reportadas simultáneamente (sin sede única): " + " / ".join(event.sites))
    return ("🚑 Llegada de ambulancia detectada\n\n" + identity(event.vehicle)
            + f"\n{site}\nHora GPS: {display(event.vehicle.gps_timestamp)}"
            + "\nLa vigilancia ha finalizado."
            + "\nBasado en la última posición reportada; no garantiza ubicación física actual.")
