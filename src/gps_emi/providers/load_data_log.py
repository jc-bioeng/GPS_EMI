"""Parameters reconstruido del JavaScript suministrado; no autentica sesiones."""
import base64
from dataclasses import dataclass
import json
import os
import re

from gps_emi.errors import AcquisitionError

STATE_FIELDS = ("intLastUpdate", "intTimer", "strMobiles", "intConsoleType",
                "idFleet", "intFrom", "strOriginQuery")
MAX_SAFE_INTEGER = 2 ** 53 - 1


class LoadDataLogConfigError(AcquisitionError):
    public_message = (
        "Configuración LoadDataLog ausente o inválida. Revise GPSPACE_SESSION_INFO "
        "y GPSPACE_LOADDATALOG_STATE con los valores observados del cliente oficial."
    )


def _key_units(key):
    # JS charCodeAt/length operan sobre unidades UTF-16, no caracteres Python.
    encoded = (key or "wtApi").encode("utf-16-le", errors="surrogatepass")
    return tuple(encoded[i] | encoded[i + 1] << 8 for i in range(0, len(encoded), 2))


def _get_obfuscation_key_byte(key: str, index: int) -> int:
    units = _key_units(key)
    return (units[index % len(units)] + index * 31 + 17) & 0xff


def obfuscate_string(text: str, key: str) -> str:
    data = text.encode("utf-8")
    units = _key_units(key)
    output = bytearray(len(data))
    for index, byte in enumerate(data):
        key_byte = (units[index % len(units)] + index * 31 + 17) & 0xff
        mixed = byte ^ key_byte
        output[index] = ((mixed << 3) | (mixed >> 5)) & 0xff
    return base64.urlsafe_b64encode(output).decode("ascii").rstrip("=")


def _supported_scalar(value):
    # No adivinar tipos por los prefijos int/str. Preservar el JSON observado.
    # Se excluyen floats: json.dumps no replica toda la notación Number de JS.
    return (value is None or type(value) in (str, bool)
            or type(value) is int and abs(value) <= MAX_SAFE_INTEGER)


def _read_object(env, name, fields):
    result = None
    try:
        def unique_object(pairs):
            obj = dict(pairs)
            if len(obj) != len(pairs):
                raise ValueError()
            return obj
        result = json.loads(env.get(name, ""), object_pairs_hook=unique_object)
    except (ValueError, TypeError, RecursionError):
        pass
    # Fuera del except: no retener JSONDecodeError.doc con datos de sesión.
    if not isinstance(result, dict) or set(result) != set(fields):
        raise LoadDataLogConfigError()
    return result


@dataclass(frozen=True, repr=False)
class WideTechSessionInfo:
    uid: str | int
    uname: str

    def __post_init__(self):
        if (type(self.uid) not in (str, int) or not _supported_scalar(self.uid)
                or isinstance(self.uid, str) and not self.uid.strip()
                or not isinstance(self.uname, str)):
            raise LoadDataLogConfigError()

    @classmethod
    def from_env(cls, env=None):
        values = _read_object(os.environ if env is None else env, "GPSPACE_SESSION_INFO", ("UID", "UNAME"))
        return cls(values["UID"], values["UNAME"])


@dataclass(frozen=True, repr=False)
class LoadDataLogState:
    intLastUpdate: object
    intTimer: object
    strMobiles: object
    intConsoleType: object
    idFleet: object
    intFrom: object
    strOriginQuery: object

    def __post_init__(self):
        if not all(_supported_scalar(getattr(self, name)) for name in STATE_FIELDS):
            raise LoadDataLogConfigError()

    @classmethod
    def from_env(cls, env=None):
        return cls(**_read_object(os.environ if env is None else env, "GPSPACE_LOADDATALOG_STATE", STATE_FIELDS))


def build_parameters(session: WideTechSessionInfo, state: LoadDataLogState) -> dict:
    return {
        "intLastUpdate": state.intLastUpdate,
        "intTimer": state.intTimer,
        "strMobiles": state.strMobiles,
        "intConsoleType": state.intConsoleType,
        "idFleet": state.idFleet,
        "bolAddDriver": True,
        "intFrom": state.intFrom,
        "strUserID": session.uid,
        "strOriginQuery": state.strOriginQuery,
    }


def serialize_parameters(parameters: dict) -> str:
    if not all(_supported_scalar(value) for value in parameters.values()):
        raise LoadDataLogConfigError()
    text = json.dumps(parameters, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    # JSON.stringify escapa surrogates aislados; combina pares UTF-16 válidos.
    text = text.encode("utf-16-le", errors="surrogatepass").decode("utf-16-le", errors="surrogatepass")
    return re.sub(r"[\ud800-\udfff]", lambda m: "\\u%04x" % ord(m.group()), text)


def generate_parameters(session: WideTechSessionInfo, state: LoadDataLogState) -> str:
    return obfuscate_string(serialize_parameters(build_parameters(session, state)), session.uname)
