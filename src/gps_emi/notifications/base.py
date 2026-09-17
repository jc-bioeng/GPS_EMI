from typing import Protocol

from gps_emi.models import ArrivalEvent


class NotificationService(Protocol):
    def send_arrival(self, event: ArrivalEvent) -> None: ...
