"""Autorización, casos de uso y adaptación WhatsApp de múltiples vigilancias."""
import logging
from threading import Thread

from gps_emi.config import WatchConfig
from gps_emi.errors import AcquisitionError
from gps_emi.monitoring.watches import WatchManager as DomainWatchManager
from gps_emi.monitoring.fleet_polling import FleetPolling
from gps_emi.queries import get_vehicle_location, get_vehicle_location_by_id, list_vehicles_at_site
from gps_emi.selection import PendingSelections, SelectionOperation, SelectionError
from gps_emi.resolution import VehicleNotFoundError, AmbiguousVehicleError
from . import formatting as fmt
from .client import WhatsAppError
from .config import normalize_number, WhatsAppConfigError
from .notifier import WhatsAppNotifier
from .routing import Conversation, State
from .menu import interactive_command
from .vehicle_selection import selection_payload

logger = logging.getLogger(__name__)


def identifier_error(code, identifier):
    if code == 'selected_unavailable':
        return "El registro seleccionado ya no está disponible de forma inequívoca. Intenta realizar la consulta nuevamente."
    if code == "not_found":
        return f'❌ No encontré la ambulancia "{identifier}".\nVerifica la placa o número de móvil e inténtalo nuevamente.'
    if code == "ambiguous":
        return "❌ El identificador es ambiguo. No se seleccionó ninguna ambulancia. Verifica placa o número de móvil."
    return fmt.GPS_ERROR


class WatchManager:
    """Adaptador WhatsApp; gestión y polling residen en monitoring."""
    def __init__(self, source_factory, messenger, config, watch_config=None, *,
                 thread_factory=Thread, autostart=True, collector=None):
        self.messenger, self.config = messenger, config
        self.selections = None
        self.selection_handler = None
        self.cancel_handler = None
        self.manager = DomainWatchManager(self._notify, watch_config)
        self.polling = FleetPolling(source_factory, self.manager, config=watch_config,
                                    on_created=self._created, on_error=self._error,
                                    on_selection=self._selection,
                                    on_terminal=lambda watch: self._reply(watch.notification_target, fmt.format_watch_failed(watch)),
                                    thread_factory=thread_factory, autostart=autostart, collector=collector)

    def _reply(self, target, text):
        try:
            self.messenger.reply(target, text)
        except WhatsAppError as error:
            logger.warning("Respuesta de vigilancia no enviada: %s.", error.category)
        except Exception:
            logger.error("Respuesta de vigilancia no enviada; fallo interno.")

    def _created(self, watch, is_new):
        text = fmt.format_watch_started(watch) if is_new else fmt.format_watch_duplicate(watch)
        self._reply(watch.notification_target, text)
        if is_new and watch.monitor.actual_sites:
            try:
                if self.cancel_handler is not None:
                    self.cancel_handler(watch.notification_target, [watch])
                self.messenger.cancel_menu(watch.notification_target, [watch])
            except WhatsAppError as error:
                logger.warning('Opción de cancelación no enviada: %s.', error.category)

    def _error(self, request, code):
        self._reply(request.notification_target, identifier_error(code, request.identifier))

    def _selection(self, request, candidates):
        if self.selection_handler is not None:
            self.selection_handler(request, candidates)
        else:
            self._error(request, 'ambiguous')

    def _notify(self, watch, event):
        notifier = WhatsAppNotifier(watch.notification_target, self.messenger, self.config)
        notifier.send_arrival(event)
        return notifier.accepted

    def start(self, sender, identifier):
        context_id = self.selections.current(sender) if self.selections is not None else None
        return self.polling.request_watch(sender, identifier, sender, context_id=context_id)

    def start_selected(self, context, vehicle_id):
        return self.polling.request_watch(context.owner_id, context.original_identifier,
                                          context.notification_target, vehicle_id=vehicle_id)

    @property
    def active(self):
        return self.polling.active

    @property
    def thread(self):
        return self.polling.thread

    @property
    def stop_event(self):
        return self.polling.stop_event

    def close(self, timeout=2):
        return self.polling.close(timeout)

    def request_stop(self):
        self.polling.request_stop()

    def list_active(self, owner_id):
        return self.manager.get_active_watches(owner_id)

    def cancel(self, owner_id, watch_id):
        return self.manager.cancel_watch(owner_id, watch_id)


class MessageService:
    """Consumido por el worker; las vigilancias comparten otro hilo de polling."""
    def __init__(self, config, messenger, watches, source_factory, watch_config=None):
        self.config, self.messenger, self.watches = config, messenger, watches
        self.source_factory = source_factory
        self.watch_config = watch_config or WatchConfig()
        self.conversation = Conversation()
        self.cancel_choices = {}
        self.vehicle_choices = {}
        self.selections = PendingSelections(config=self.watch_config)
        self.watches.selections = self.selections
        self.watches.selection_handler = self._watch_selection
        self.watches.cancel_handler = self._set_cancel_choices

    def _set_cancel_choices(self, sender, watches):
        self.vehicle_choices.pop(sender, None)
        self.cancel_choices[sender] = [watch.watch_id for watch in watches]
        self.conversation.states[sender] = State.WAITING_CANCEL

    def _show_selection(self, sender, context, page=0):
        rows = selection_payload(context, self.watch_config, page)['action']['sections'][0]['rows']
        self.messenger.vehicle_selection(sender, context, self.watch_config, page)
        self.vehicle_choices[sender] = [interactive_command(row['id']) for row in rows]

    def _offer_selection(self, sender, operation, identifier, candidates, target, generation):
        try:
            context = self.selections.offer(sender, operation, identifier, candidates, target, generation)
            if context is not None:
                self._show_selection(sender, context)
        except SelectionError:
            self._feedback(sender, 'Los registros son ambiguos y no se pueden distinguir de forma segura con los datos disponibles. No se seleccionó ninguna ambulancia.')
        except WhatsAppError as error:
            logger.warning('Selector no enviado: %s.', error.category)

    def _watch_selection(self, request, candidates):
        self._offer_selection(request.owner_id, SelectionOperation.CREATE_WATCH,
                              request.identifier, candidates, request.notification_target, request.context_id)

    def _feedback(self, sender, text):
        try:
            self.messenger.reply(sender, text)
        except WhatsAppError as error:
            logger.warning("Feedback no enviado: %s.", error.category)

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
        text = message.text.strip()
        choices = self.vehicle_choices.get(sender)
        if choices and text.isascii() and text.isdigit():
            if len(text) > 6 or not 1 <= int(text) <= len(choices):
                self._feedback(sender, '_Responde con un número de la lista o escribe MENU._')
                return
            text = choices[int(text) - 1]
        command = self.conversation.route(sender, text)
        if command.action != 'vehicle_page':
            self.vehicle_choices.pop(sender, None)
        generation = (self.selections.begin(sender)
                      if command.action not in ('vehicle_select', 'vehicle_page') else None)
        if command.action not in ('cancel', 'cancel_id'):
            self.cancel_choices.pop(sender, None)
        logger.info("Comando reconocido: %s.", command.action)
        try:
            if command.action == "menu":
                self.messenger.menu(sender)
                return
            elif command.action == 'cancel_operation':
                response = 'Operación cancelada. Las vigilancias activas no se modificaron.'
            elif command.action in ('vehicle_select', 'vehicle_page'):
                parts = command.argument.split(':')
                if len(parts) != 2:
                    raise SelectionError('invalid')
                selection_id, choice = parts
                if command.action == 'vehicle_page':
                    context = self.selections.view(sender, selection_id)
                    if not choice.isascii() or not choice.isdigit() or len(choice) > 6:
                        raise SelectionError('invalid')
                    page = int(choice)
                    if page >= (len(context.candidates) + 7) // 8:
                        raise SelectionError('invalid')
                    self._show_selection(sender, context, page)
                    return
                context, vehicle_id = self.selections.consume(sender, selection_id, choice)
                if context.operation == SelectionOperation.LOCATION:
                    self._feedback(sender, '🔎 Consultando el registro seleccionado...')
                    try:
                        result = get_vehicle_location_by_id(self.source_factory(), vehicle_id, self.watch_config)
                    except (VehicleNotFoundError, AmbiguousVehicleError):
                        response = identifier_error('selected_unavailable', '')
                    else:
                        response = fmt.format_location(result)
                elif context.operation == SelectionOperation.CREATE_WATCH:
                    self._feedback(sender, '🔎 Buscando el registro seleccionado...')
                    if self.watches.start_selected(context, vehicle_id):
                        return
                    response = '⚠️ El servicio de vigilancias está detenido.'
                else:
                    raise SelectionError('invalid')
            elif command.action == "watch_menu":
                self.messenger.watch_menu(sender)
                return
            elif command.action == "list_watches":
                response = fmt.format_watches(self.watches.list_active(sender))
            elif command.action == "prompt_cancel":
                watches = self.watches.list_active(sender)
                self.cancel_choices[sender] = [watch.watch_id for watch in watches]
                if watches:
                    self.conversation.states[sender] = State.WAITING_CANCEL
                    response = fmt.format_watches(watches, cancelling=True)
                    if len(watches) <= 10:
                        try:
                            self.messenger.cancel_menu(sender, watches)
                            return
                        except WhatsAppError:
                            logger.warning('Lista de cancelación no enviada; se reenvía como respuesta.')
                else:
                    response = fmt.NO_WATCHES
            elif command.action == "cancel_id":
                watch = self.watches.cancel(sender, command.argument)
                self.cancel_choices.pop(sender, None)
                response = fmt.format_watch_cancelled(watch) if watch else "Esa vigilancia no está activa o no te pertenece. Escribe DETENER para actualizar la lista."
            elif command.action == "cancel":
                choices = self.cancel_choices.get(sender, [])
                number = command.argument
                if number.isascii() and number.isdigit() and len(number) <= 6 and 1 <= int(number) <= len(choices):
                    watch = self.watches.cancel(sender, choices[int(number) - 1])
                    response = fmt.format_watch_cancelled(watch) if watch else "Esa vigilancia ya no está activa. Escribe DETENER para actualizar la lista."
                    self.cancel_choices.pop(sender, None)
                else:
                    self.conversation.states[sender] = State.WAITING_CANCEL
                    response = "Selecciona un número de la lista o escribe MENU."
            elif command.action == "reply":
                response = command.argument
            elif command.action == "watch":
                self._feedback(sender, f"🔎 Buscando {command.argument}...")
                if self.watches.start(sender, command.argument):
                    return  # Confirmación tras resolver en el snapshot central.
                response = "⚠️ El servicio de vigilancias está detenido."
            elif command.action == "location":
                self._feedback(sender, f"🔎 Consultando {command.argument}...")
                result = get_vehicle_location(self.source_factory(), command.argument, self.watch_config)
                logger.info("Consulta de ubicación ejecutada.")
                response = fmt.format_location(result)
            elif command.action == "site":
                self._feedback(sender, f"🔎 Consultando ambulancias en {fmt.site_name(command.argument)}...")
                result = list_vehicles_at_site(self.source_factory(), command.argument, self.watch_config)
                logger.info("Consulta de sede ejecutada.")
                response = fmt.format_site(result)
            else:
                response = fmt.HELP
        except VehicleNotFoundError:
            response = identifier_error("not_found", command.argument)
        except AmbiguousVehicleError as error:
            if command.action == 'location' and error.candidates:
                self._offer_selection(sender, SelectionOperation.LOCATION, command.argument,
                                      error.candidates, sender, generation)
                return
            response = identifier_error("ambiguous", command.argument)
        except SelectionError as error:
            response = ('La selección anterior expiró. Realiza la consulta nuevamente.' if error.code == 'expired'
                        else 'La selección no es válida o ya fue utilizada. Realiza la consulta nuevamente.')
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
