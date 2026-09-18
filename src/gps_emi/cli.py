import argparse
import logging
import math
import sys

from dotenv import load_dotenv

from gps_emi.config import WatchConfig
from gps_emi.monitoring.arrival import DESTINATIONS
from gps_emi.monitoring.runner import WatchRunner
from gps_emi.notifications.base import NotificationService
from gps_emi.notifications.console import ConsoleNotifier
from gps_emi.providers.widetech import WideTechClient, WideTechError

logger = logging.getLogger(__name__)


def configure_logging(level):
    app_logger = logging.getLogger("gps_emi")
    app_logger.setLevel(level)
    app_logger.propagate = False
    for handler in list(app_logger.handlers):
        if getattr(handler, "gps_emi_console", False):
            app_logger.removeHandler(handler)
            handler.close()
    handler = logging.StreamHandler(sys.stdout)
    handler.gps_emi_console = True
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%H:%M:%S"))
    app_logger.addHandler(handler)


def positive_interval(value):
    try:
        interval = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("El intervalo debe ser un número positivo.") from None
    if not math.isfinite(interval) or interval <= 0:
        raise argparse.ArgumentTypeError("El intervalo debe ser finito y mayor que cero.")
    return interval


def watch(client, identifier: str, destination: str, interval: float,
          notifier: NotificationService, sleep=None, *, now=None,
          initial_backoff=5.0, max_backoff=30.0, stale_warning_seconds=300.0) -> int:
    config = WatchConfig(interval, initial_backoff, max_backoff, stale_warning_seconds)
    return WatchRunner(client, identifier, destination, notifier, config,
                       sleep=sleep, now=now).run()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GPS EMI — Monitor de llegada")
    parser.add_argument("--identifier", "--plate", dest="identifier",
                        help="Placa o número de móvil de una ambulancia Medellín")
    parser.add_argument("--destination", choices=DESTINATIONS)
    parser.add_argument("--interval", type=positive_interval, default=30.0,
                        help="Segundos entre consultas (predeterminado: 30)")
    parser.add_argument("--initial-backoff", type=positive_interval, default=5.0,
                        help="Espera inicial tras fallo transitorio (segundos: 5)")
    parser.add_argument("--max-backoff", type=positive_interval, default=30.0,
                        help="Espera máxima tras fallos consecutivos (segundos: 30)")
    parser.add_argument("--stale-warning-seconds", type=float, default=300.0,
                        help="Advertir STALE si report_age supera este umbral (300)")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    args = parser.parse_args(argv)
    try:
        WatchConfig(args.interval, args.initial_backoff, args.max_backoff, args.stale_warning_seconds)
    except ValueError as error:
        parser.error(str(error))
    configure_logging(args.log_level)
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
        return watch(WideTechClient(), identifier, destination, args.interval, ConsoleNotifier(),
                     initial_backoff=args.initial_backoff, max_backoff=args.max_backoff,
                     stale_warning_seconds=args.stale_warning_seconds)
    except (KeyboardInterrupt, EOFError):
        logger.info("Vigilancia cancelada.")
        return 130
    except WideTechError as error:
        logger.error("%s", error.public_message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
