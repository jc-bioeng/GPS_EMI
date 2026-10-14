"""Parser y máquina de estados independientes del transporte y de GPS."""
from dataclasses import dataclass
from enum import Enum
import unicodedata

from gps_emi.sites import EMI_SITES
from . import formatting as fmt


class State(str, Enum):
    IDLE = "IDLE"
    WAITING_WATCH_IDENTIFIER = "WAITING_WATCH_IDENTIFIER"
    WAITING_LOCATION_IDENTIFIER = "WAITING_LOCATION_IDENTIFIER"
    WAITING_SITE = "WAITING_SITE"
    WAITING_CANCEL = "WAITING_CANCEL"
    WATCH_MENU = "WATCH_MENU"


@dataclass(frozen=True)
class Command:
    action: str
    argument: str = ""


SITES = {"POBLADO": EMI_SITES[0], "TALLER": EMI_SITES[1], "1": EMI_SITES[0], "2": EMI_SITES[1]}

# Match whole command words, longest first; never normalize vehicle identifiers.
COMMAND_ALIASES = {
    'MENU': ('menu', 'inicio', 'principal', 'menu principal'),
    'AYUDA': ('ayuda', 'help'),
    'VIGILAR': ('vigilar', 'vigilancia', 'vigila', 'iniciar vigilancia', 'nueva vigilancia'),
    'UBICACION': ('ubicacion', 'ubica', 'ubicar', 'localizar', 'localiza', 'consultar ubicacion'),
    'VIGILANCIAS': ('vigilancias', 'gestionar vigilancias'),
    'MISVIGILANCIAS': ('misvigilancias', 'mis vigilancias', 'ver vigilancias', 'listar vigilancias'),
    'DETENER': ('detener', 'detener vigilancia', 'detener vigilancias', 'parar vigilancia', 'parar vigilancias'),
    'CANCELAR': ('cancelar', 'cancela'),
    'SEDE': ('sede', 'ver sede', 'consultar sede'),
}


def _command_key(word):
    return ''.join(c for c in unicodedata.normalize('NFD', word.casefold())
                   if not unicodedata.combining(c))


def canonical_command(text):
    words = text.strip().split()
    normalized = [_command_key(word) for word in words]
    aliases = sorted(((alias.split(), canonical) for canonical, variants in COMMAND_ALIASES.items()
                      for alias in variants), key=lambda item: len(item[0]), reverse=True)
    for prefix, canonical in aliases:
        if normalized[:len(prefix)] == prefix:
            parts = text.strip().split(maxsplit=len(prefix))
            argument = parts[-1] if len(parts) > len(prefix) else ''
            return canonical + (' ' + argument if argument else '')
    return text


def parse_command(text):
    parts = canonical_command(text).strip().split(maxsplit=1)
    if not parts:
        return None
    verb = parts[0].upper()
    argument = parts[1].strip() if len(parts) == 2 else ""
    simple = {"MENU": "menu", "MENÚ": "menu", "INICIO": "menu", "AYUDA": "help",
              "VIGILANCIAS": "watch_menu", "MISVIGILANCIAS": "list_watches", "DETENER": "prompt_cancel"}
    if verb in simple:
        return Command(simple[verb]) if not argument else Command("invalid")
    if verb == "CANCELAR":
        return Command("cancel_id", argument) if argument else Command("cancel_operation")
    if verb in ('VEHICLE_SELECT', 'VEHICLE_PAGE'):
        return Command('vehicle_select' if verb == 'VEHICLE_SELECT' else 'vehicle_page', argument)
    if verb in ("VIGILAR", "UBICACION", "UBICACIÓN"):
        action = "watch" if verb == "VIGILAR" else "location"
        return Command(action, argument) if argument else Command("prompt_" + action)
    if verb == "SEDE":
        if not argument:
            return Command("prompt_site")
        return Command("site", SITES[argument.upper()]) if argument.upper() in SITES else Command("invalid")
    return None


class Conversation:
    def __init__(self):
        self.states = {}

    def route(self, sender, text):
        command = parse_command(text)
        state = self.states.get(sender, State.IDLE)
        if command is None:
            stripped = text.strip()
            if state == State.WATCH_MENU:
                command = Command({'1': 'prompt_watch', '2': 'list_watches',
                                   '3': 'prompt_cancel', '4': 'menu'}.get(stripped, 'watch_menu'))
            elif state == State.WAITING_CANCEL:
                command = Command("cancel", stripped)
            elif state == State.WAITING_SITE:
                command = Command("site", SITES[stripped.upper()]) if stripped.upper() in SITES else Command("retry_site")
            elif state in (State.WAITING_LOCATION_IDENTIFIER, State.WAITING_WATCH_IDENTIFIER):
                action = "watch" if state == State.WAITING_WATCH_IDENTIFIER else "location"
                command = Command(action, stripped) if stripped else Command("prompt_" + action)
            else:
                action = {"1": "prompt_watch", "2": "prompt_location", "3": "prompt_site", "4": "help", "5": "watch_menu"}.get(stripped, "invalid")
                command = Command(action)
        self.states.pop(sender, None)
        if command.action == 'watch_menu':
            self.states[sender] = State.WATCH_MENU
        prompts = {
            "prompt_watch": (State.WAITING_WATCH_IDENTIFIER, fmt.identifier_prompt(True)),
            "prompt_location": (State.WAITING_LOCATION_IDENTIFIER, fmt.identifier_prompt()),
            "prompt_site": (State.WAITING_SITE, fmt.SITE_PROMPT),
            "retry_site": (State.WAITING_SITE, "Selecciona 1 o 2.\n" + fmt.SITE_PROMPT),
        }
        if command.action in prompts:
            new_state, response = prompts[command.action]
            self.states[sender] = new_state
            return Command("reply", response)
        if command.action == "menu":
            return Command("menu", fmt.MENU)
        responses = {"help": fmt.HELP,
                     "invalid": "No entendí el comando. Escribe MENU o AYUDA."}
        return Command("reply", responses[command.action]) if command.action in responses else command
