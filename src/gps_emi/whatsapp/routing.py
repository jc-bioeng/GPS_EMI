"""Parser y máquina de estados independientes del transporte y de GPS."""
from dataclasses import dataclass
from enum import Enum

from gps_emi.sites import EMI_SITES
from . import formatting as fmt


class State(str, Enum):
    IDLE = "IDLE"
    WAITING_WATCH_IDENTIFIER = "WAITING_WATCH_IDENTIFIER"
    WAITING_LOCATION_IDENTIFIER = "WAITING_LOCATION_IDENTIFIER"
    WAITING_SITE = "WAITING_SITE"


@dataclass(frozen=True)
class Command:
    action: str
    argument: str = ""


SITES = {"POBLADO": EMI_SITES[0], "TALLER": EMI_SITES[1], "1": EMI_SITES[0], "2": EMI_SITES[1]}


def parse_command(text):
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return None
    verb = parts[0].upper()
    argument = parts[1].strip() if len(parts) == 2 else ""
    simple = {"MENU": "menu", "MENÚ": "menu", "INICIO": "menu", "AYUDA": "help"}
    if verb in simple:
        return Command(simple[verb]) if not argument else Command("invalid")
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
            if state == State.WAITING_SITE:
                command = Command("site", SITES[stripped.upper()]) if stripped.upper() in SITES else Command("retry_site")
            elif state in (State.WAITING_LOCATION_IDENTIFIER, State.WAITING_WATCH_IDENTIFIER):
                action = "watch" if state == State.WAITING_WATCH_IDENTIFIER else "location"
                command = Command(action, stripped) if stripped else Command("prompt_" + action)
            else:
                action = {"1": "prompt_watch", "2": "prompt_location", "3": "prompt_site", "4": "help"}.get(stripped, "invalid")
                command = Command(action)
        self.states.pop(sender, None)
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
        responses = {"menu": fmt.MENU, "help": fmt.HELP,
                     "invalid": "No entendí el comando. Escribe MENU o AYUDA."}
        return Command("reply", responses[command.action]) if command.action in responses else command
