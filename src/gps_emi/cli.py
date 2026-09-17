import argparse
import math
import time
from datetime import datetime

from dotenv import load_dotenv

from gps_emi.monitoring.arrival import ArrivalMonitor, DESTINATIONS
from gps_emi.monitoring.observation import observe_resolved_vehicle
from gps_emi.notifications.base import NotificationService
from gps_emi.notifications.console import ConsoleNotifier
from gps_emi.providers.widetech import WideTechClient, WideTechError
from gps_emi.resolution import find_vehicle, VehicleResolutionError


def positive_interval(value):
    try:
        interval = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("El intervalo debe ser un número positivo.") from None
    if not math.isfinite(interval) or interval <= 0:
        raise argparse.ArgumentTypeError("El intervalo debe ser finito y mayor que cero.")
    return interval


def watch(client, identifier: str, destination: str, interval: float,
          notifier: NotificationService, sleep=time.sleep) -> int:
    monitor = None
    while True:
        try:
            vehicle = find_vehicle(client.get_vehicles(), identifier)
        except VehicleResolutionError as error:
            print(f"ERROR: {error} Vigilancia detenida; no se infiere una salida de geocerca.")
            return 1
        if monitor is None:
            monitor = ArrivalMonitor(vehicle.display_identifier, destination)
            print(f"Vigilando {identifier.strip()} → {destination}")
        event = observe_resolved_vehicle(monitor, vehicle)
        membership = "INSIDE" if destination in vehicle.zones else "OUTSIDE"
        print(f"[{datetime.now():%H:%M:%S}] {membership} | última posición reportada: "
              f"{vehicle.gps_timestamp or 'fecha no disponible'} | GPSFix={vehicle.gps_fix}")
        if vehicle.gps_fix in (0, False, "0"):
            print("ADVERTENCIA: GPSFix=0; el reporte no garantiza una posición GPS válida.")
        elif vehicle.gps_fix is None:
            print("ADVERTENCIA: GPSFix no disponible.")
        if vehicle.gps_timestamp is None:
            print("ADVERTENCIA: fecha GPS no disponible; no se puede evaluar antigüedad.")
        if event:
            notifier.send_arrival(event)
            print("Vigilancia completada.")
            return 0
        sleep(interval)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GPS EMI — Monitor de llegada")
    parser.add_argument("--identifier", "--plate", dest="identifier",
                        help="Placa o número de móvil de una ambulancia Medellín")
    parser.add_argument("--destination", choices=DESTINATIONS)
    parser.add_argument("--interval", type=positive_interval, default=30.0,
                        help="Segundos entre consultas (predeterminado: 30)")
    args = parser.parse_args(argv)
    try:
        print("GPS EMI — Monitor de llegada")
        identifier = (args.identifier if args.identifier is not None
                      else input("Placa o número de móvil: ")).strip().upper()
        if not identifier:
            print("ERROR: introduzca una placa o número de móvil.")
            return 1
        destination = args.destination
        if destination is None:
            print("Destino:\n1. EMI Medellin_Poblado\n2. EMI_Medellin_Taller")
            choice = input("> ").strip()
            if choice not in ("1", "2"):
                print("ERROR: seleccione 1 o 2.")
                return 1
            destination = DESTINATIONS[int(choice) - 1]
        # Solo en ejecución explícita de CLI. Nunca al importar ni en el dominio.
        load_dotenv(dotenv_path=".env", override=False)
        return watch(WideTechClient(), identifier, destination, args.interval, ConsoleNotifier())
    except (KeyboardInterrupt, EOFError):
        print("\nVigilancia cancelada.")
        return 130
    except WideTechError as error:
        print(f"ERROR: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
