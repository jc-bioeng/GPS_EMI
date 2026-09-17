from gps_emi.models import ArrivalEvent


class ConsoleNotifier:
    def send_arrival(self, event: ArrivalEvent) -> None:
        print("=" * 40)
        print(event.event_type)
        print(f"{event.vehicle.display_identifier} llegó a {event.destination}")
        print(f"Hora GPS reportada: {event.vehicle.gps_timestamp or 'no disponible'}")
        print("=" * 40)
