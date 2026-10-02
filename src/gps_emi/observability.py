"""Logging común y métricas en memoria, exclusivamente operacionales."""
import logging
import os
import sys
import time
from threading import Event, Lock, Thread
from gps_emi.clock import OperationalFormatter


def configure_logging(level=None):
    level = level or os.environ.get('LOG_LEVEL', 'INFO').upper()
    if level not in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
        level = 'INFO'
    logger = logging.getLogger('gps_emi')
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        if getattr(handler, 'gps_emi_console', False):
            logger.removeHandler(handler)
            handler.close()
    handler = logging.StreamHandler(sys.stdout)
    handler.gps_emi_console = True
    handler.setFormatter(OperationalFormatter('[%(asctime)s] %(levelname)s: %(message)s [%(name)s]'))
    logger.addHandler(handler)


class Metrics:
    def __init__(self, now=time.monotonic):
        self.now, self.started = now, now()
        self.lock = Lock()
        self.values = dict(provider_status='IDLE', acquisitions=0, provider_failures=0,
                           vehicles_last_snapshot=0, active_watches=0, collection_session='NONE',
                           observations_written=0, collector_errors=0, dropped_snapshots=0)
        self.failure_since = None

    def update(self, **values):
        with self.lock:
            self.values.update(values)

    def increment(self, **values):
        with self.lock:
            for key, amount in values.items():
                self.values[key] += amount

    def provider(self, status, vehicles=0):
        logger = logging.getLogger('gps_emi.provider')
        with self.lock:
            previous = self.values['provider_status']
            self.values['provider_status'] = status
            if status == 'PROVIDER_OK':
                self.values['acquisitions'] += 1
                self.values['vehicles_last_snapshot'] = vehicles
                if self.failure_since is not None:
                    logger.info('provider recovered downtime_seconds=%.1f', self.now() - self.failure_since)
                self.failure_since = None
            else:
                self.values['provider_failures'] += 1
                if self.failure_since is None:
                    self.failure_since = self.now()
            if status != previous:
                level = logging.INFO if status == 'PROVIDER_OK' else (
                    logging.WARNING if status in ('NETWORK_ERROR', 'EMPTY_RESPONSE', 'HTTP_TRANSIENT') else logging.ERROR)
                logger.log(level, 'provider_status=%s', status)

    def summary(self):
        with self.lock:
            values = dict(self.values)
        logging.getLogger('gps_emi.runtime').info('operational_summary uptime_seconds=%.0f %s',
            self.now() - self.started, ' '.join(f'{key}={value}' for key, value in values.items()))


metrics = Metrics()


class SummaryReporter:
    def __init__(self, watch_count=None):
        self.watch_count = watch_count
        try:
            self.interval = max(1, int(os.environ.get('GPS_EMI_LOG_SUMMARY_SECONDS', '300')))
        except ValueError:
            self.interval = 300
        self.stop = Event()
        self.thread = Thread(target=self._run, name='gps-emi-summary', daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        while not self.stop.wait(self.interval):
            if self.watch_count is not None:
                metrics.update(active_watches=self.watch_count())
            metrics.summary()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1)
