"""Opciones estables del menú nativo y equivalencias de conversación."""
import re
OPTIONS = (
    ("watch_arrival", "Vigilar llegada", "VIGILAR"),
    ("vehicle_location", "Consultar ubicación", "UBICACION"),
    ("vehicles_at_site", "Ver ambulancias en sede", "SEDE"),
    ("help", "Ayuda", "AYUDA"),
)
COMMANDS = {identifier: command for identifier, _, command in OPTIONS}
WATCH_OPTIONS = (
    ('new_watch', 'Nueva vigilancia', 'VIGILAR'),
    ('my_watches', 'Mis vigilancias', 'MISVIGILANCIAS'),
    ('stop_watch', 'Detener vigilancia', 'DETENER'),
    ('main_menu', 'Menú', 'MENU'),
)
COMMANDS.update({identifier: command for identifier, _, command in WATCH_OPTIONS})
COMMANDS['manage_watches'] = 'VIGILANCIAS'


def interactive_command(selection):
    if not isinstance(selection, str):
        return None
    if selection in COMMANDS:
        return COMMANDS[selection]
    if re.fullmatch(r'vehicle_select:[0-9a-f]{32}:[0-9a-f]{32}', selection):
        return 'VEHICLE_SELECT ' + selection.split(':', 1)[1]
    if re.fullmatch(r'vehicle_page:[0-9a-f]{32}:[0-9]{1,6}', selection):
        return 'VEHICLE_PAGE ' + selection.split(':', 1)[1]
    if re.fullmatch(r'cancel_watch:[0-9a-f]{32}', selection):
        return 'CANCELAR ' + selection.split(':', 1)[1]
    return None


def cancel_menu_payload(watches):
    if not 1 <= len(watches) <= 10:
        raise ValueError('La selección nativa admite entre una y diez filas.')
    return {'type': 'list', 'header': {'type': 'text', 'text': '⏹️ Detener vigilancia'},
            'body': {'text': 'Selecciona la vigilancia que deseas detener.'},
            'action': {'button': 'Seleccionar', 'sections': [{'title': 'Vigilancias', 'rows': [
                {'id': 'cancel_watch:' + watch.watch_id,
                 'title': (watch.mobile_number or watch.plate or 'Ambulancia')[:24],
                 'description': ('Placa: ' + (watch.plate or 'N/D'))[:72]}
                for watch in watches]}]}}


def menu_payload(*, watches=False):
    options = WATCH_OPTIONS if watches else OPTIONS + (('manage_watches', 'Gestionar vigilancias', 'VIGILANCIAS'),)
    return {"type": "list", "header": {"type": "text", "text": "🚑 Vigilancias" if watches else "🚑 GPS EMI — Biomédica"},
            "body": {"text": "¿Qué deseas hacer?"},
            "footer": {"text": "También puedes escribir un comando directamente."},
            "action": {"button": "Ver opciones", "sections": [{"title": "Opciones", "rows": [
                {"id": identifier, "title": title} for identifier, title, _ in options]}]}}
