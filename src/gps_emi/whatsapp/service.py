"""Autorización, ejecución de casos de uso y una única vigilancia del piloto."""
import logging
from threading import Event, Lock, Thread

from gps_emi.config import WatchConfig
from gps_emi.errors import AcquisitionError
from gps_emi.monitoring.runner import WatchRunner
from gps_emi.queries import get_vehicle_location, list_vehicles_at_site
from gps_emi.resolution import VehicleNotFoundError, AmbiguousVehicleError
from . import formatting as fmt
from .client import WhatsAppError
from .config import normalize_number, WhatsAppConfigError
from .notifier import WhatsAppNotifier
from .routing import Conversation

logger = logging.getLogger(__name__)


def identifier_error(code, identifier):
    if code == "not_found":
        return f'❌ No encontré la ambulancia "{identifier}".\nVerifica la placa o número de móvil e inténtalo nuevamente.'
    if code == "ambiguous":
        return "❌ El identificador es ambiguo. No se seleccionó ninguna ambulancia. Verifica placa o número de móvil."
    return fmt.GPS_ERROR


class WatchManager:
    """Reserva atómica global; ciclo de vida explícito, sin HTTP en el webhook."""
    def __init__(self, source_factory, messenger, config, watch_config=None, *,
                 runner_factory=WatchRunner, thread_factory=Thread):
        self.source_factory, self.messenger, self.config = source_factory, messenger, config
        self.watch_config = watch_config or WatchConfig()
        self.runner_factory, self.thread_factory = runner_factory, thread_factory
        self.lock, self.stop_event = Lock(), Event()
        self.active = False
        self.closed = False
        self.thread = None
        self.last_runner = None
        self.last_notifier = None

    def _reply(self, sender, text):
        try:
            self.messenger.reply(sender, text)
        except WhatsAppError as error:
            logger.warning("Respuesta de vigilancia no enviada: %s.", error.category)
        except Exception:
            logger.error("Respuesta de vigilancia no enviada; fallo interno.")

    def start(self, sender, identifier):
        with self.lock:
            if self.active or self.closed:
                return False
            self.active = True
            self.stop_event.clear()
            try:
                self.thread = self.thread_factory(target=self._run, args=(sender, identifier),
                                                  name="gps-emi-watch", daemon=True)
                self.thread.start()
            except Exception:
                self.active = False
                raise
        logger.info("Solicitud de vigilancia aceptada.")
        return True

    def _run(self, sender, identifier):
        try:
            notifier = WhatsAppNotifier(sender, self.messenger, self.config)
            self.last_notifier = notifier
            runner = self.runner_factory(
                self.source_factory(), identifier, None, notifier, self.watch_config,
                stop_event=self.stop_event,
                on_resolved=lambda vehicle: self._reply(sender, fmt.format_started(vehicle)),
            )
            self.last_runner = runner
            result = runner.run()
            if result == 1 and not self.stop_event.is_set():
                self._reply(sender, identifier_error(runner.failure_code, identifier))
        except Exception:
            logger.error("Vigilancia finalizada por fallo interno; sin detalles sensibles.")
            if not self.stop_event.is_set():
                self._reply(sender, fmt.GPS_ERROR)
        finally:
            with self.lock:
                self.active = False

    def close(self, timeout=2):
        with self.lock:
            self.closed = True
            self.stop_event.set()
            thread = self.thread
        if thread is not None:
            thread.join(timeout=timeout)
        # Peticiones HTTP en curso no se pueden interrumpir: timeout del proveedor.
        return thread is None or not thread.is_alive()


class MessageService:
    """Consumido secuencialmente por el worker. El watch usa un hilo separado."""
    def __init__(self, config, messenger, watches, source_factory, watch_config=None):
        self.config, self.messenger, self.watches = config, messenger, watches
        self.source_factory = source_factory
        self.watch_config = watch_config or WatchConfig()
        self.conversation = Conversation()

    def handle(self, message):
        try:
            sender = normalize_number(message.sender)
        except WhatsAppConfigError:
            logger.warning("Remitente sin número internacional válido; mensaje ignorado.")
            return
        authorized = sender in self.config.allowed_numbers
        logger.info("Mensaje recibido; remitente %s.", "autorizado" if authorized else "no autorizado")
        # No retener ventanas ni estado de desconocidos; a lo sumo una denegación.
        if not authorized:
            try:
                if self.messenger.windows.timestamp_is_open(message.timestamp):
                    self.messenger.client.send_text(sender, fmt.DENIED)
            except WhatsAppError:
                logger.warning("No se pudo enviar denegación de acceso.")
            return
        if not self.messenger.windows.note(sender, message.timestamp):
            logger.warning("Mensaje fuera de ventana; no se ejecutan consultas ni texto libre.")
            return
        command = self.conversation.route(sender, message.text)
        logger.info("Comando reconocido: %s.", command.action)
        try:
            if command.action == "reply":
                response = command.argument
            elif command.action == "watch":
                if self.watches.start(sender, command.argument):
                    return  # Confirmación con identidad real al resolver el runner.
                response = fmt.BUSY
            elif command.action == "location":
                result = get_vehicle_location(self.source_factory(), command.argument, self.watch_config)
                logger.info("Consulta de ubicación ejecutada.")
                response = fmt.format_location(result)
            elif command.action == "site":
                result = list_vehicles_at_site(self.source_factory(), command.argument, self.watch_config)
                logger.info("Consulta de sede ejecutada.")
                response = fmt.format_site(result)
            else:
                response = fmt.HELP
        except VehicleNotFoundError:
            response = identifier_error("not_found", command.argument)
        except AmbiguousVehicleError:
            response = identifier_error("ambiguous", command.argument)
        except AcquisitionError:
            logger.warning("Consulta GPS no disponible; error de adquisición.")
            response = fmt.GPS_ERROR
        except Exception:
            logger.error("Operación no completada; error interno sin detalles sensibles.")
            response = "⚠️ No fue posible completar la operación. Inténtalo nuevamente."
        try:
            self.messenger.reply(sender, response)
        except WhatsAppError as error:
            logger.warning("Respuesta no enviada: %s. Sin reintento automático.", error.category)
