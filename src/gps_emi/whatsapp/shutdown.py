"""Señales del proceso y cierre acotado, sin red ni persistencia."""
import logging
import signal
import time
from threading import Event
from waitress.wasyncore import ExitNow

logger = logging.getLogger(__name__)


class ShutdownRequested(ExitNow):
    """Escapa callbacks de wasyncore sin activar su logging de error ni el
    cierre implícito de Waitress para KeyboardInterrupt/SystemExit.
    """


class Shutdown:
    def __init__(self):
        self.stopping = Event()
        self.signum = None
        self.previous = {}

    def handle(self, signum, frame):
        if not self.stopping.is_set():
            self.signum = signum
            self.stopping.set()
            raise ShutdownRequested()

    def install(self):
        for number in (signal.SIGTERM, signal.SIGINT):
            self.previous[number] = signal.signal(number, self.handle)

    def restore(self):
        for number, handler in self.previous.items():
            signal.signal(number, handler)

    def close(self, inbox, watches, server, timeout=6):
        self.stopping.set()
        deadline = time.monotonic() + timeout
        def remaining():
            return max(0, deadline - time.monotonic())
        def attempt(action):
            try:
                return action()
            except Exception:
                logger.warning("Un componente no completó el cierre; sin detalles internos.")
        # Señalar ambos consumidores antes de esperar cualquiera de ellos.
        for component in (inbox, watches):
            if component is not None:
                attempt(component.request_stop)
        if server is not None:
            # Cierra todos los sockets, incluidos listeners IPv4/IPv6 y canales.
            # Evita MultiSocketServer.close(), cuyo shutdown tiene timeout propio.
            from waitress import wasyncore
            socket_map = getattr(server, "_map", None)
            if socket_map is None:
                socket_map = getattr(server, "map", None)
            if isinstance(socket_map, dict):
                attempt(lambda: wasyncore.close_all(socket_map))
            else:
                attempt(server.close)
            attempt(lambda: server.task_dispatcher.shutdown(timeout=remaining()))
        for component in (inbox, watches):
            if component is not None:
                if attempt(lambda: component.close(timeout=remaining())) is False:
                    logger.warning("Cierre con trabajo en curso; se agotó la espera del componente.")
