"""Configuración explícita del canal; nunca lee archivos ni representa secretos."""
from dataclasses import dataclass, field
import os
import re


class WhatsAppConfigError(ValueError):
    pass


def normalize_number(value: str) -> str:
    # No adivinar país ni aceptar letras/BSUID como un número autorizado.
    if not isinstance(value, str) or not re.fullmatch(r"\+?[0-9 ()-]+", value.strip()):
        raise WhatsAppConfigError("Número inválido; utilice formato internacional con código de país.")
    number = re.sub(r"[ ()-]", "", value.strip()).lstrip("+")
    if not re.fullmatch(r"[1-9][0-9]{6,14}", number):
        raise WhatsAppConfigError("Número internacional inválido.")
    return number


@dataclass(frozen=True, repr=False)
class WhatsAppConfig:
    access_token: str = field(repr=False)
    phone_number_id: str = field(repr=False)
    verify_token: str = field(repr=False)
    app_secret: str = field(repr=False)
    allowed_numbers: frozenset[str] = field(repr=False)
    api_version: str = "v25.0"
    arrival_mode: str = "template"
    template_name: str = "ambulance_arrival_notification"
    template_language: str = "es"

    def __post_init__(self):
        for name in ("access_token", "phone_number_id", "verify_token", "app_secret"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n"):
                raise WhatsAppConfigError(f"Configuración WhatsApp ausente o inválida: {name}.")
        if not re.fullmatch(r"[0-9]+", self.phone_number_id):
            raise WhatsAppConfigError("Phone Number ID inválido.")
        if not re.fullmatch(r"v[0-9]+\.[0-9]+", self.api_version):
            raise WhatsAppConfigError("Versión Graph API inválida.")
        if not self.allowed_numbers:
            raise WhatsAppConfigError("Configure al menos un número autorizado.")
        object.__setattr__(self, "allowed_numbers", frozenset(normalize_number(n) for n in self.allowed_numbers))
        if self.arrival_mode not in ("template", "text"):
            raise WhatsAppConfigError("El modo de llegada debe ser template o text.")
        if not re.fullmatch(r"[a-z0-9_]+", self.template_name):
            raise WhatsAppConfigError("Nombre de plantilla inválido.")
        if not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", self.template_language):
            raise WhatsAppConfigError("Idioma de plantilla inválido.")

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        return cls(
            access_token=env.get("WHATSAPP_ACCESS_TOKEN", "").strip(),
            phone_number_id=env.get("WHATSAPP_PHONE_NUMBER_ID", "").strip(),
            verify_token=env.get("WHATSAPP_VERIFY_TOKEN", "").strip(),
            app_secret=env.get("WHATSAPP_APP_SECRET", "").strip(),
            allowed_numbers=frozenset(n.strip() for n in env.get("WHATSAPP_ALLOWED_NUMBERS", "").split(",") if n.strip()),
            api_version=env.get("WHATSAPP_API_VERSION", "v25.0").strip(),
            arrival_mode=env.get("WHATSAPP_ARRIVAL_MODE", "template").strip(),
            template_name=env.get("WHATSAPP_ARRIVAL_TEMPLATE", "ambulance_arrival_notification").strip(),
            template_language=env.get("WHATSAPP_TEMPLATE_LANGUAGE", "es").strip(),
        )
