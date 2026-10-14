import argparse
import logging
import math

from dotenv import load_dotenv

from gps_emi.config import WatchConfig
from gps_emi.acquisition_runtime import AcquisitionRuntime
from gps_emi.observability import configure_logging
from gps_emi.monitoring.arrival import DESTINATIONS
from gps_emi.monitoring.runner import watch_arrival
from gps_emi.errors import TransientAcquisitionError
from gps_emi.formatting import format_location, format_site_inventory
from gps_emi.notifications.base import NotificationService
from gps_emi.notifications.console import ConsoleNotifier
from gps_emi.errors import AcquisitionError
from gps_emi.queries import get_vehicle_location, list_vehicles_at_site
from gps_emi.resolution import VehicleResolutionError
from gps_emi.sites import matching_sites

logger = logging.getLogger('gps_emi.cli')


def positive_interval(value):
    try:
        interval = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("El intervalo debe ser un número positivo.") from None
    if not math.isfinite(interval) or interval <= 0:
        raise argparse.ArgumentTypeError("El intervalo debe ser finito y mayor que cero.")
    return interval


def watch(client, identifier: str, destination: str | None, interval: float,
          notifier: NotificationService, sleep=None, *, now=None,
          initial_backoff=5.0, max_backoff=30.0, stale_warning_seconds=300.0, inactivity_seconds=43200.0,
          confirm_inside=None) -> int:
    config = WatchConfig(interval, initial_backoff, max_backoff, stale_warning_seconds, inactivity_seconds)
    return watch_arrival(client, identifier, notifier, config,
                         destination=destination, sleep=sleep, now=now, confirm_inside=confirm_inside)


def _confirm_inside(vehicle):
    print(f'La última posición reportada de {vehicle.display_identifier} está en '
          f'{", ".join(matching_sites(vehicle.zones))}. Hora GPS: {vehicle.gps_timestamp}.')
    print('No garantiza su ubicación actual. Todavía no se ha iniciado la vigilancia.')
    return input('¿Vigilar para que salga y vuelva a entrar? [s/N] (válido 5 minutos): ').strip().casefold() in ('s', 'si', 'sí')


def _select_site() -> str:
    print("Sede:\n1. EMI Medellin_Poblado\n2. EMI_Medellin_Taller")
    while True:
        choice = input("> ").strip()
        if choice in ("1", "2"):
            return DESTINATIONS[int(choice) - 1]
        print("ERROR: seleccione 1 o 2.")


def _execute(action, args, config) -> int:
    # Solo coordina entrada, configuración local, caso de uso y presentación.
    if action in ("watch", "location"):
        identifier = (args.identifier if args.identifier is not None
                      else input("Placa o número de móvil: ")).strip().upper()
        if not identifier:
            raise ValueError("Introduzca una placa o número de móvil.")
    else:
        site = args.site if args.site is not None else _select_site()
    # Igual carga local que I1/I2, únicamente al ejecutar una operación.
    load_dotenv(dotenv_path=".env", override=False)
    configure_logging(args.log_level)
    if getattr(args, '_runtime', None) is None:
        args._runtime = AcquisitionRuntime(official=args.official, interval=args.interval,
                                           max_backoff=args.acquisition_max_backoff)
        args._runtime.start()
    client = args._runtime.source
    if client.coordinator.peek() is None:
        print('Adquisición GPS inicializando; esperando el primer snapshot válido.')
    if action == "watch":
        if args.destination is not None:
            logger.warning("--destination está obsoleto: conserva el modo de una sola sede de I2. "
                           "Omítalo para vigilar la llegada a cualquiera de las sedes EMI.")
        return watch(client, identifier, args.destination, config.polling_interval, ConsoleNotifier(),
                     initial_backoff=config.initial_backoff, max_backoff=config.max_backoff,
                     stale_warning_seconds=config.stale_warning_seconds, inactivity_seconds=config.inactivity_seconds,
                     confirm_inside=_confirm_inside)
    if action == "location":
        client = client.bind(client.wait())
        print(format_location(get_vehicle_location(client, identifier, config)))
    else:
        client = client.bind(client.wait())
        print(format_site_inventory(list_vehicles_at_site(client, site, config)))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GPS EMI — Vigilancia y consultas")
    parser.add_argument('--official', action='store_true', help='Activar RenderExcel explícitamente')
    parser.add_argument('--acquisition-max-backoff', type=positive_interval, default=300)
    parser.add_argument("--action", choices=("watch", "location", "site"),
                        help="Operación directa; sin argumentos se muestra el menú")
    parser.add_argument("--identifier", "--plate", dest="identifier",
                        help="Placa o móvil: consultas oficiales nacionales; vigilancias solo Medellín")
    parser.add_argument("--destination", choices=DESTINATIONS,
                        help="Obsoleto: vigilancia de una sola sede, compatibilidad I2")
    parser.add_argument("--site", choices=DESTINATIONS, help="Sede para consultar inventario")
    parser.add_argument("--interval", type=positive_interval, default=30.0,
                        help="Segundos entre consultas (predeterminado: 30)")
    parser.add_argument("--initial-backoff", type=positive_interval, default=5.0,
                        help="Compatibilidad: el backoff central inicia en --interval")
    parser.add_argument("--max-backoff", type=positive_interval, default=30.0,
                        help="Compatibilidad: use --acquisition-max-backoff para adquisición")
    parser.add_argument("--stale-warning-seconds", type=float, default=300.0,
                        help="Advertir STALE si report_age supera este umbral (300)")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default=None)
    parser.add_argument("--watch-inactivity-seconds", type=float, default=43200,
                        help="Vencimiento por inactividad individual, segundos (43200)")
    args = parser.parse_args(argv)
    action = args.action or ("site" if args.site is not None else "watch")
    if args.destination is not None and action != "watch":
        parser.error("--destination solo corresponde a la vigilancia histórica.")
    if args.site is not None and action != "site":
        parser.error("--site solo corresponde al inventario por sede.")
    if args.identifier is not None and action == "site":
        parser.error("El inventario por sede no requiere --identifier.")
    try:
        config = WatchConfig(args.interval, args.initial_backoff, args.max_backoff, args.stale_warning_seconds, args.watch_inactivity_seconds)
    except ValueError as error:
        parser.error(str(error))
    configure_logging(args.log_level)
    try:
        print("GPS EMI")
        if any(value is not None for value in (args.action, args.identifier, args.destination, args.site)):
            return _execute(action, args, config)
        while True:
            print("\n1. Vigilar llegada a EMI\n2. Consultar ubicación de ambulancia"
                  "\n3. Ver ambulancias en sede\n0. Salir")
            choice = input("> ").strip()
            if choice == "0":
                return 0
            if choice not in ("1", "2", "3"):
                print("ERROR: seleccione 0, 1, 2 o 3.")
                continue
            try:
                result = _execute({"1": "watch", "2": "location", "3": "site"}[choice], args, config)
            except (VehicleResolutionError, ValueError) as error:
                print(f"ERROR: {error}")
                continue
            if result != 0:
                return result
    except (KeyboardInterrupt, EOFError):
        logger.info("Operación cancelada.")
        return 130
    except TransientAcquisitionError:
        logger.error("No se obtuvo una adquisición dentro del tiempo disponible; vuelva a consultar.")
        return 1
    except AcquisitionError as error:
        logger.error("%s", error.public_message)
        return 1
    except (VehicleResolutionError, ValueError) as error:
        logger.error("%s", error)
        return 1
    except Exception:
        logger.error("No se pudo completar la operación; no se muestran detalles internos.")
        return 1
    finally:
        if getattr(args, '_runtime', None) is not None:
            args._runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
