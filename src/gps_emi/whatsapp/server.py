"""Entrada explícita del piloto local, un proceso, sin reloader."""
import argparse
import logging

from dotenv import load_dotenv
from waitress import create_server

from gps_emi.cli import configure_logging
from gps_emi.config import WatchConfig
from gps_emi.providers.widetech import WideTechClient
from .client import WhatsAppClient
from .config import WhatsAppConfig, WhatsAppConfigError
from .delivery import Messenger, ServiceWindow
from .service import MessageService, WatchManager
from .webhook import create_app, MAX_BODY_BYTES
from .worker import Inbox

logger = logging.getLogger(__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description="GPS EMI — piloto WhatsApp I4-P")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--initial-backoff", type=float, default=5)
    parser.add_argument("--max-backoff", type=float, default=30)
    parser.add_argument("--stale-warning-seconds", type=float, default=300)
    args = parser.parse_args(argv)
    configure_logging("INFO")
    if not 1 <= args.port <= 65535:
        parser.error("Puerto fuera de rango.")
    inbox = watches = server = None
    try:
        watch_config = WatchConfig(args.interval, args.initial_backoff, args.max_backoff, args.stale_warning_seconds)
        load_dotenv(dotenv_path=".env", override=False)
        config = WhatsAppConfig.from_env()
        messenger = Messenger(WhatsAppClient(config), ServiceWindow())
        watches = WatchManager(WideTechClient, messenger, config, watch_config)
        service = MessageService(config, messenger, watches, WideTechClient, watch_config)
        inbox = Inbox(service.handle)
        app = create_app(config, inbox)
        server = create_server(app, host=args.host, port=args.port, threads=4,
                               max_request_body_size=MAX_BODY_BYTES, channel_timeout=30)
        inbox.start()
        logger.info("Piloto WhatsApp disponible en %s:%s/webhook; una sola instancia.", args.host, args.port)
        server.run()
        return 0
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
        if watches is not None:
            watches.close()
        if inbox is not None:
            inbox.close()
        if server is not None:
            server.close()


if __name__ == "__main__":
    raise SystemExit(main())
