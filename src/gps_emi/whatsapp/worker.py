"""Cola limitada, deduplicación atómica y un consumidor en memoria."""
from collections import deque
import logging
from threading import Condition, Thread
import time

logger = logging.getLogger(__name__)


class Inbox:
    def __init__(self, handler, *, capacity=100, seen_capacity=10000,
                 ttl=7 * 24 * 60 * 60, now=None):
        self.handler = handler
        self.capacity, self.seen_capacity, self.ttl = capacity, seen_capacity, ttl
        self.now = now or time.monotonic
        self.pending = deque()
        self.seen = {}
        self.condition = Condition()
        self.closed = False
        self.thread = None

    def submit(self, messages):
        with self.condition:
            if self.closed:
                return False
            now = self.now()
            self.seen = {key: expiry for key, expiry in self.seen.items() if expiry > now}
            unique = {}
            for message in messages:
                if message.message_id not in self.seen:
                    unique.setdefault(message.message_id, message)
            fresh = list(unique.values())
            # Reserva todo el lote o ninguno: un 503 no deja IDs parcialmente vistos.
            if len(self.pending) + len(fresh) > self.capacity or len(self.seen) + len(fresh) > self.seen_capacity:
                logger.warning("Cola o registro de deduplicación lleno; webhook debe reintentarse.")
                return False
            for message in fresh:
                self.seen[message.message_id] = now + self.ttl
                self.pending.append(message)
            if len(fresh) < len(messages):
                logger.info("Mensaje duplicado ignorado.")
            self.condition.notify()
            return True

    def _process(self, message):
        try:
            self.handler(message)
        except Exception:
            logger.error("Procesamiento de mensaje fallido; sin volcar payload ni excepción.")

    def process_one(self):
        """Punto de ejecución determinista para tests sin iniciar hilos."""
        with self.condition:
            if not self.pending or self.closed:
                return False
            message = self.pending.popleft()
        self._process(message)
        return True

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or bool(self.pending))
                if self.closed:
                    return
                message = self.pending.popleft()
            self._process(message)

    def start(self):
        with self.condition:
            if self.closed:
                raise RuntimeError("La cola está cerrada.")
            if self.thread is None:
                self.thread = Thread(target=self._run, name="gps-emi-messages", daemon=True)
                self.thread.start()

    def close(self, timeout=2):
        with self.condition:
            self.closed = True
            self.pending.clear()
            self.condition.notify_all()
        if self.thread is not None:
            self.thread.join(timeout=timeout)
        return self.thread is None or not self.thread.is_alive()
