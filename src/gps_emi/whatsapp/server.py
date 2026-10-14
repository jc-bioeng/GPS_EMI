"""Entrada explícita del piloto local, un proceso, sin reloader."""
import argparse
import logging
import signal
import time
from importlib.metadata import version

from dotenv import load_dotenv
from waitress import create_server

from gps_emi.cli import configure_logging
from gps_emi.config import WatchConfig
from gps_emi.acquisition_runtime import AcquisitionRuntime
from gps_emi.analysis.collector import start_collector
from gps_emi.observability import SummaryReporter
from .client import WhatsAppClient
from .config import WhatsAppConfig, WhatsAppConfigError
from .delivery import Messenger, ServiceWindow
from .service import MessageService, WatchManager
from .webhook import create_app, MAX_BODY_BYTES
from .worker import Inbox
from .shutdown import Shutdown, ShutdownRequested

logger = logging.getLogger("gps_emi.whatsapp.server")


def main(argv=None):
    parser = argparse.ArgumentParser(description="GPS EMI — piloto WhatsApp I4-P")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument('--official', action='store_true', help='Activar RenderExcel explícitamente')
    parser.add_argument('--acquisition-max-backoff', type=float, default=300)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--initial-backoff", type=float, default=5)
    parser.add_argument("--max-backoff", type=float, default=30)
    parser.add_argument("--stale-warning-seconds", type=float, default=300)
    parser.add_argument("--watch-inactivity-seconds", type=float, default=43200,
                        help="Vencimiento por inactividad individual, segundos (43200)")
    args = parser.parse_args(argv)
    configure_logging(None)
    started = time.monotonic()
    if not 1 <= args.port <= 65535:
        parser.error("Puerto fuera de rango.")
    inbox = watches = server = collector = reporter = runtime = None
    shutdown = Shutdown()
    try:
        shutdown.install()
        watch_config = WatchConfig(args.interval, args.initial_backoff, args.max_backoff, args.stale_warning_seconds, args.watch_inactivity_seconds)
        load_dotenv(dotenv_path=".env", override=False)
        configure_logging(None)
        config = WhatsAppConfig.from_env()
        messenger = Messenger(WhatsAppClient(config), ServiceWindow())
        runtime = AcquisitionRuntime(official=args.official, interval=args.interval,
                                     max_backoff=args.acquisition_max_backoff)
        def source_factory():
            if shutdown.stopping.is_set():
                raise RuntimeError("El proceso está cerrando.")
            return runtime.source
        collector = start_collector()
        watches = WatchManager(source_factory, messenger, config, watch_config, collector=collector)
        if collector is not None:
            watches.polling.start()
        service = MessageService(config, messenger, watches, source_factory, watch_config)
        inbox = Inbox(service.handle, on_idle=service.drain_pending)
        app = create_app(config, inbox)
        server = create_server(app, host=args.host, port=args.port, threads=4,
                               max_request_body_size=MAX_BODY_BYTES, channel_timeout=30)
        runtime.start()
        inbox.start()
        reporter = SummaryReporter(watches.manager.active_count, runtime.coordinator.health)
        reporter.start()
        logger.info('service started version=%s polling_seconds=%s summary_seconds=%s', version('gps-emi'), args.interval, reporter.interval)
        logger.info('acquisition mode=%s query_scope=%s watch_scope=medellin',
                    'official' if args.official else 'legacy',
                    'national_ambulances' if args.official else 'medellin')
        logger.info("Piloto WhatsApp disponible en %s:%s/webhook; una sola instancia.", args.host, args.port)
        server.run()
        return 0
    except ShutdownRequested:
        logger.info("Deteniendo piloto WhatsApp por señal.")
        return 130 if shutdown.signum == signal.SIGINT else 0
    except KeyboardInterrupt:
        logger.info("Deteniendo piloto WhatsApp.")
        return 130
    except (WhatsAppConfigError, ValueError):
        logger.error("Configuración del piloto ausente o inválida; revise las variables y opciones documentadas.")
        return 1
    except Exception:
        logger.error("No se pudo ejecutar el piloto; revise configuración y disponibilidad del puerto.")
        return 1
    finally:
        try:
            if runtime is not None:
                runtime.request_stop()
            shutdown.close(inbox, watches, server)
        finally:
            try:
                if collector is not None:
                    collector.close(timeout=2)
                if reporter is not None:
                    reporter.close()
                if runtime is not None:
                    runtime.close()
                logger.info('service shutdown finished uptime_seconds=%.1f', time.monotonic()-started)
            finally:
                shutdown.restore()


if __name__ == "__main__":
    raise SystemExit(main())
