import argparse
import math
import time
from datetime import datetime

from dotenv import load_dotenv

from gps_emi.models import normalize_plate
from gps_emi.monitoring.arrival import ArrivalMonitor, DESTINATIONS
from gps_emi.notifications.base import NotificationService
from gps_emi.notifications.console import ConsoleNotifier
from gps_emi.providers.widetech import WideTechClient, WideTechError


def positive_interval(value):
    try:
        interval = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("El intervalo debe ser un número positivo.") from None
    if not math.isfinite(interval) or interval <= 0:
        raise argparse.ArgumentTypeError("El intervalo debe ser finito y mayor que cero.")
    return interval


def watch(client, plate: str, destination: str, interval: float,
          notifier: NotificationService, sleep=time.sleep) -> int:
    monitor = ArrivalMonitor(plate, destination)
    print(f"Vigilando {monitor.plate} → {destination}")
    while True:
        matches = [v for v in client.get_vehicles()
                   if normalize_plate(v.plate) == monitor.plate]
        if len(matches) != 1:
            print("ERROR: la placa no existe o no es única entre Ambulancias Medellín. "
                  "Vigilancia detenida; no se infiere una salida de geocerca.")
            return 1
        vehicle = matches[0]
        event = monitor.observe(vehicle)
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
    parser.add_argument("--plate", help="Placa de una ambulancia Medellín")
    parser.add_argument("--destination", choices=DESTINATIONS)
    parser.add_argument("--interval", type=positive_interval, default=30.0,
                        help="Segundos entre consultas (predeterminado: 30)")
    args = parser.parse_args(argv)
    try:
        print("GPS EMI — Monitor de llegada")
        plate = normalize_plate(args.plate if args.plate is not None else input("Placa: "))
        if not plate:
            print("ERROR: introduzca una placa.")
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
        return watch(WideTechClient(), plate, destination, args.interval, ConsoleNotifier())
    except (KeyboardInterrupt, EOFError):
        print("\nVigilancia cancelada.")
        return 130
    except WideTechError as error:
        print(f"ERROR: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
