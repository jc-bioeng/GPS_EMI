"""Test-only snapshot sources. No production adapter or scheduling fallback."""
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from itertools import count
from unittest.mock import Mock

from gps_emi.acquisition import (AcquisitionConfig, Coordinator, LegacyAcquisition,
                                 Snapshot, SnapshotSource, SnapshotUnavailable)


class ScriptedSnapshots(SnapshotSource):
    """Drive the real coordinator with fake time, explicitly from the test."""
    def __init__(self, transport, interval=30, utcnow=None):
        self.transport = transport
        self.time = 0
        coordinator = Coordinator(LegacyAcquisition(transport), AcquisitionConfig(interval=interval, pending_timeout=10000),
            monotonic=lambda: self.time,
            utcnow=utcnow or (lambda: datetime(2026, 9, 17, 17, 35, tzinfo=timezone.utc)+timedelta(seconds=self.time)))
        super().__init__(coordinator)

    def advance(self):
        self.time = max(self.time, self.coordinator.next_start)
        self.coordinator.tick()

    def wait(self, timeout=120, *, after_version=None, stop_event=None):
        pending = self.coordinator.request(refresh=after_version is not None, after_version=after_version)
        for _ in range(32):
            if stop_event is not None and stop_event.is_set():
                pending.cancel()
                raise KeyboardInterrupt()
            if pending.done():
                return pending.result()
            self.advance()
        pending.cancel()
        raise SnapshotUnavailable()


def publish(polling):
    """One fake scheduler step and one real consumer step."""
    if polling.active:
        polling.source.advance()
    return polling.cycle()


def snapshot_reader(source):
    """Structural snapshot mock for business/presentation tests (no HTTP).

    Each peek represents an explicitly supplied new publication; read counts
    in those tests count snapshot reads, not network acquisitions.
    Scheduling/coalescence is tested with the real coordinator separately.
    """
    versions = count(1)
    def published():
        return Snapshot('test', next(versions), datetime(2026, 9, 17, tzinfo=timezone.utc), None)
    def request(**kwargs):
        future = Future()
        future.set_result(published())
        return future
    source.coordinator = Mock(closed=False, blocked=False,
                              config=AcquisitionConfig(), probes=[], subscribers=[])
    source.coordinator.monotonic.return_value = 0
    source.coordinator.peek.side_effect = published
    source.coordinator.request.side_effect = request
    source.bind = Mock(return_value=source)
    source.wait = Mock(side_effect=lambda **kwargs: published())
    return source
