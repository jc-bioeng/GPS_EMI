"""Política única de ventana de atención y segmentación de texto."""
import math
from threading import Lock
import time

from .client import TEXT_LIMIT, WhatsAppError

SERVICE_WINDOW_SECONDS = 24 * 60 * 60


class ServiceWindow:
    def __init__(self, *, now=None):
        self.now = now or time.time
        self.last_inbound = {}
        self.lock = Lock()

    def note(self, sender, timestamp):
        current = self.now()
        if not math.isfinite(timestamp) or timestamp > current + 60:
            return False
        with self.lock:
            self.last_inbound[sender] = max(timestamp, self.last_inbound.get(sender, timestamp))
        return self.is_open(sender)

    def is_open(self, sender):
        with self.lock:
            timestamp = self.last_inbound.get(sender)
        return timestamp is not None and self.timestamp_is_open(timestamp)

    def timestamp_is_open(self, timestamp):
        return math.isfinite(timestamp) and -60 <= self.now() - timestamp < SERVICE_WINDOW_SECONDS


def split_text(text, limit=TEXT_LIMIT):
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit + 1)
        if cut <= 0:
            cut = limit
        yield text[:cut]
        text = text[cut:].lstrip("\n")
    if text:
        yield text


class Messenger:
    def __init__(self, client, windows):
        self.client, self.windows = client, windows

    def reply(self, recipient, text):
        for part in split_text(text):
            if not self.windows.is_open(recipient):
                raise WhatsAppError("service_window_closed")
            self.client.send_text(recipient, part)

    def menu(self, recipient):
        if not self.windows.is_open(recipient):
            raise WhatsAppError("service_window_closed")
        return self.client.send_menu(recipient)

    def watch_menu(self, recipient):
        if not self.windows.is_open(recipient):
            raise WhatsAppError("service_window_closed")
        return self.client.send_watch_menu(recipient)

    def cancel_menu(self, recipient, watches):
        if not self.windows.is_open(recipient):
            raise WhatsAppError("service_window_closed")
        return self.client.send_cancel_menu(recipient, watches)

    def vehicle_selection(self, recipient, context, config=None, page=0):
        if not self.windows.is_open(recipient):
            raise WhatsAppError('service_window_closed')
        return self.client.send_vehicle_selection(recipient, context, config, page)
