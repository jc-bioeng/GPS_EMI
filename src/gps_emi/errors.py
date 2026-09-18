"""Errores de adquisición con mensajes públicos independientes del detalle original."""


class AcquisitionError(RuntimeError):
    public_message = "Error no recuperable durante la adquisición de datos."

    def __init__(self, message=None):
        super().__init__(message or self.public_message)


class TransientAcquisitionError(AcquisitionError):
    public_message = "No se pudo conectar con GPSpace temporalmente; se volverá a intentar."


class EmptyResponseError(TransientAcquisitionError):
    public_message = "El endpoint devolvió una respuesta vacía temporalmente; se volverá a intentar."


class SessionExpiredError(AcquisitionError):
    public_message = (
        "La sesión de GPSpace no es válida o expiró. "
        "Inicie sesión y actualice la configuración de autenticación local."
    )


class MissingCredentialsError(AcquisitionError):
    public_message = "Falta la variable de entorno requerida para autenticar GPSpace."


class InvalidResponseError(AcquisitionError):
    public_message = (
        "Respuesta WideTech no reconocida o sin datos. La sesión puede haber expirado "
        "o el formato del proveedor cambió; revise la sesión y la configuración."
    )


class HTTPAcquisitionError(AcquisitionError):
    def __init__(self, status_code):
        self.public_message = f"WideTech no respondió correctamente (HTTP {int(status_code)})."
        super().__init__()


class TransientHTTPError(HTTPAcquisitionError, TransientAcquisitionError):
    """HTTP recuperable según la política explícita del adaptador."""
