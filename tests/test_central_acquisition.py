"""Phase 2: deterministic scheduler, no network and no real sleeps."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
from unittest.mock import Mock

import pytest

from gps_emi.acquisition import (AcquisitionConfig, Coordinator, SnapshotSource, SnapshotUnavailable,
                                 CoordinatorClosed, LabelMapping, LegacyAcquisition)
from gps_emi.acquisition_runtime import HostLease, AuthorityBusy, AcquisitionRuntime
from gps_emi.providers.widetech_official import (parse_render_excel, OfficialAcquisitionError,
                                               ErrorKind, RetryAfter, Diagnostic)
from gps_emi.models import Vehicle
from gps_emi.monitoring.fleet_polling import FleetPolling
from gps_emi.monitoring.watches import WatchManager
from gps_emi.queries import get_vehicle_location, get_vehicle_location_by_id, list_vehicles_at_site
from gps_emi.sites import EMI_SITES


class Clock:
    value = 0
    def mono(self):
        return self.value
    def utc(self):
        return datetime(2026, 1, 1, tzinfo=timezone.utc)+timedelta(seconds=self.value)
    def advance(self, seconds):
        self.value += seconds


def rig(*responses, config=None):
    clock, transport = Clock(), Mock()
    transport.acquire.side_effect = responses
    central = Coordinator(transport, config, monotonic=clock.mono, utcnow=clock.utc)
    return central, SnapshotSource(central), clock, transport


def row():
    return Vehicle('synthetic-id', 'TEST1', datetime(2025, 12, 31, 19), mobile_number='TEST-MOBILE', zones=[EMI_SITES[0]])


def test_demand_coalesces_queries_watches_campaign_and_cache():
    central, source, clock, transport = rig((row(),), (row(),))
    collector = Mock(active=True)
    manager = WatchManager(Mock())
    fleet = FleetPolling(lambda: source, manager, collector=collector, autostart=False)
    fleet.request_watch('a', 'TEST1', 'a')
    fleet.request_watch('b', 'TEST1', 'b')
    futures = [central.request(refresh=True) for _ in range(10)]
    assert central.tick()
    fleet.cycle()
    first = central.peek()
    assert all(f.result() is first for f in futures)
    assert transport.acquire.call_count == 1
    assert manager.active_count() == 2
    assert collector.submit.call_count == 1
    for query in (lambda: get_vehicle_location(source, 'TEST1'),
                  lambda: get_vehicle_location_by_id(source, 'synthetic-id'),
                  lambda: list_vehicles_at_site(source, EMI_SITES[0])):
        result = query()
        assert result.acquisition.acquired_at == first.acquired_at
    fleet.cycle()
    assert collector.submit.call_count == 1
    assert central.health()['successes'] == 1
    clock.advance(30)
    central.tick()
    fleet.cycle()
    assert collector.submit.call_count == 2  # same GPS report, new acquisition
    assert manager.active_count() == 2
    assert central.peek().acquired_at != first.acquired_at


def test_copies_are_isolated_and_cache_age_does_not_reset():
    central, source, clock, _ = rig((row(),))
    central.request(); central.tick()
    original = central.peek()
    source.get_vehicles()[0].zones.clear()
    assert source.get_vehicles()[0].zones == [EMI_SITES[0]]
    clock.advance(900)
    result = get_vehicle_location(source, 'TEST1')
    assert result.acquisition.age_seconds == 900
    assert central.request().result() is original
    assert central.peek().acquired_at == original.acquired_at


@pytest.mark.parametrize('kind', [ErrorKind.HTTP, ErrorKind.PAYLOAD, ErrorKind.RESTRICTION])
def test_failure_retains_last_valid(kind):
    central, source, clock, _ = rig((row(),), OfficialAcquisitionError(kind, status=500))
    central.demand('watch', True)
    central.tick(); original = central.peek()
    clock.advance(30)
    assert not central.tick()
    assert central.peek() is original and source.get_vehicles()
    assert central.health()['state'] == 'UNAVAILABLE'
    assert central.health()['errors'] == 1


def test_first_snapshot_absent_pending_bounded_and_ttl():
    central, source, clock, transport = rig(config=AcquisitionConfig(capacity=1, pending_timeout=9))
    first = central.request()
    with pytest.raises(SnapshotUnavailable):
        central.request().result()
    with pytest.raises(SnapshotUnavailable):
        source.get_vehicles()
    clock.advance(9)
    assert not central.tick()
    with pytest.raises(SnapshotUnavailable):
        first.result()
    transport.acquire.assert_not_called()


def test_interval_no_catchup_idle_reactivation_and_grouping():
    central, _, clock, transport = rig((row(),), (row(),), (row(),), config=AcquisitionConfig(interval=17))
    assert not central.tick()
    central.request(); central.tick()
    pending = [central.request(refresh=True) for _ in range(5)]
    clock.advance(16); assert not central.tick()
    clock.advance(1); assert central.tick()
    assert all(f.done() for f in pending)
    clock.advance(1000)
    assert not central.tick()  # inactive
    central.demand('new-watch', True)
    assert central.tick()
    for _ in range(20):
        assert not central.tick()
    assert transport.acquire.call_count == 3


def test_backoff_gradual_recovery_and_retry_after_date():
    error = OfficialAcquisitionError(ErrorKind.RESTRICTION, functional_code=109,
                                    retry_after=RetryAfter(seconds=75))
    central, _, clock, _ = rig(error, error, error, (row(),), (row(),), (row(),))
    central.demand('watch', True)
    central.tick(); assert central.next_start == 75
    clock.advance(74); assert not central.tick()
    clock.advance(1); central.tick(); assert central.backoff == 60
    clock.advance(75); central.tick(); assert central.backoff == 120
    clock.advance(120); central.tick(); assert central.backoff == 60
    clock.advance(60); central.tick(); assert central.backoff == 30
    clock.advance(30); central.tick(); assert central.backoff == 0
    failure = OfficialAcquisitionError(ErrorKind.HTTP, retry_after=RetryAfter(at=clock.utc()+timedelta(seconds=250)))
    central.source.acquire.side_effect = [failure]
    clock.advance(30); central.tick()
    assert central.health()['wait'] == 220


def test_108_blocks_this_method_not_cache_and_never_retries():
    central, _, clock, transport = rig((row(),), OfficialAcquisitionError(ErrorKind.AUTHORIZATION, functional_code=108))
    central.demand('watch', True); central.tick()
    saved = central.peek()
    clock.advance(30); central.tick()
    assert central.blocked and central.health()['state'] == 'BLOCKED_METHOD'
    assert central.request().result() is saved
    with pytest.raises(SnapshotUnavailable):
        central.request(refresh=True).result()
    clock.advance(9999); assert not central.tick()
    assert transport.acquire.call_count == 2


def test_overlap_and_close_during_inflight_discard_publication():
    entered, release = Event(), Event()
    def blocking():
        entered.set()
        assert release.wait(3)
        return (row(),)
    central, _, _, transport = rig()
    transport.acquire.side_effect = blocking
    pending = central.request()
    thread = Thread(target=central.tick)
    thread.start()
    assert entered.wait(3)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert not any(pool.map(lambda _: central.tick(), range(20)))
    assert central.close(timeout=0) is False
    with pytest.raises(CoordinatorClosed):
        pending.result()
    release.set(); thread.join(3)
    assert central.peek() is None
    assert not central.tick()
    assert transport.acquire.call_count == 1


def test_official_quality_evidence_and_timezone_projection():
    payload = (Path(__file__).parent/'fixtures'/'render_excel.xml').read_bytes()
    result = parse_render_excel(payload)
    clean = replace(result, diagnostics=(), duplicate_ids=(), incomplete_rows=())
    partial = replace(clean, diagnostics=(Diagnostic('incomplete_record', 1),))
    central, _, clock, _ = rig(clean, partial)
    source = SnapshotSource(central, LabelMapping('VEH_NAM', 'Movil'))
    central.demand('watch', True); central.tick()
    first = central.peek()
    assert len(first.records) == len(result.records)
    assert first.coverage == 'unknown'
    for v in source.get_vehicles():
        original = next(r for r in first.records if r.vehicle_id == v.vehid)
        assert v.gps_timestamp.tzinfo is None
        assert v.gps_timestamp.hour == original.gps_timestamp.hour
    clock.advance(30); assert central.tick()
    assert central.peek().version == first.version + 1
    assert central.received().diagnostics == partial.diagnostics
    assert central.health()['rejected'] == 0


def test_host_exclusion_and_persistent_deadline(tmp_path):
    path = tmp_path/'authority.lock'
    lease = HostLease(path)
    now = datetime.now(timezone.utc)
    lease.reserve(now, 123)
    with pytest.raises(AuthorityBusy):
        HostLease(path)
    lease.close()
    replacement = HostLease(path)
    assert replacement.remaining(now) == 123
    replacement.close()


def test_new_compatibility_clients_do_not_acquire(tmp_path):
    from gps_emi.providers.widetech import WideTechClient, load_data_log
    from gps_emi.errors import AcquisitionError
    with pytest.raises(AcquisitionError):
        WideTechClient().get_vehicles()
    with pytest.raises(AcquisitionError):
        load_data_log()
    transport = Mock()
    runtime = AcquisitionRuntime(source=transport, lock_path=tmp_path/'lock')
    try:
        with pytest.raises(SnapshotUnavailable):
            WideTechClient().get_vehicles()
        transport.acquire.assert_not_called()
    finally:
        assert runtime.close()


def test_second_process_cannot_become_cli_or_server_authority(tmp_path):
    import subprocess
    import sys
    path = tmp_path/'shared-installation.lock'
    code = '''
import sys
from gps_emi.acquisition_runtime import HostLease, AuthorityBusy
try:
    lease = HostLease(sys.argv[1])
except AuthorityBusy:
    raise SystemExit(23)
lease.close()
'''
    first = HostLease(path)
    try:
        child = subprocess.run([sys.executable, '-c', code, str(path)], capture_output=True, timeout=10)
        assert child.returncode == 23
    finally:
        first.close()
    child = subprocess.run([sys.executable, '-c', code, str(path)], capture_output=True, timeout=10)
    assert child.returncode == 0


def test_cli_real_composition_official_with_fake_transport(monkeypatch, tmp_path, capsys):
    import requests
    from gps_emi import cli
    from gps_emi.providers.widetech_official import RequestsTransport
    payload = (Path(__file__).parent/'fixtures'/'render_excel.xml').read_bytes()
    response = requests.Response()
    response.status_code = 200
    response._content = payload
    response._content_consumed = True
    transport = Mock(return_value=response)
    monkeypatch.setattr(RequestsTransport, 'post', transport)
    monkeypatch.setenv('WIDETECH_LOGIN', 'synthetic-login')
    monkeypatch.setenv('WIDETECH_PASSWORD', 'synthetic-password')
    monkeypatch.setenv('WIDETECH_PLATE_FIELD', 'VEH_NAM')
    monkeypatch.setenv('WIDETECH_MOBILE_FIELD', 'Movil')
    # Drive the sole real scheduler deterministically from the test, without a thread.
    monkeypatch.setattr(Coordinator, 'start', lambda self: None)
    def wait(self):
        future = self.coordinator.request()
        self.coordinator.tick()
        return future.result(timeout=0)
    monkeypatch.setattr(SnapshotSource, 'wait', wait)
    assert cli.main(['--official', '--action', 'site', '--site', EMI_SITES[0]]) == 0
    transport.assert_called_once()
    assert 'Última adquisición:' in capsys.readouterr().out
    # Both entrypoints import this same composition and stable lock-path function.
    from gps_emi.whatsapp import server
    assert server.AcquisitionRuntime is cli.AcquisitionRuntime


def test_idle_backoff_cannot_be_reset_and_old_cache_requests_refresh():
    central, source, clock, transport = rig((row(),), OfficialAcquisitionError(
        ErrorKind.RESTRICTION, retry_after=RetryAfter(seconds=180)), (row(),))
    central.request(); central.tick()
    clock.advance(30)
    assert central.request().result().version == 1
    assert len(central.pending) == 1  # old cache schedules one shared refresh
    central.tick()
    central.pending.clear()  # no remaining caller; a later caller cannot reset the deadline
    clock.advance(179)
    central.request(refresh=True)
    assert not central.tick()
    clock.advance(1)
    assert central.tick() and transport.acquire.call_count == 3


def test_lock_remains_held_until_inflight_transport_finishes(tmp_path):
    entered, release = Event(), Event()
    path = tmp_path/'inflight.lock'
    def acquire():
        entered.set()
        assert release.wait(3)
        return (row(),)
    central = Coordinator(Mock(acquire=acquire), lease=HostLease(path))
    central.request(); central.start()
    try:
        assert entered.wait(3)
        assert not central.close(timeout=0)
        with pytest.raises(AuthorityBusy):
            HostLease(path)
    finally:
        release.set()
        assert central.close(timeout=3)
    lease = HostLease(path)
    assert lease.remaining(datetime.now(timezone.utc)) > 0
    lease.close()


def test_backoff_cap_and_wall_clock_changes_do_not_schedule_requests():
    errors = [OfficialAcquisitionError(ErrorKind.HTTP, status=500) for _ in range(6)]
    central, _, clock, transport = rig(*errors, config=AcquisitionConfig(interval=11, max_backoff=44))
    central.demand('watch', True)
    delays = []
    for _ in errors:
        central.tick()
        delays.append(central.health()['wait'])
        clock.advance(delays[-1])
    assert delays == [11, 22, 44, 44, 44, 44]
    central.utcnow = lambda: datetime(2099, 1, 1, tzinfo=timezone.utc)
    central.next_start = clock.mono()+11
    assert not central.tick()
    assert transport.acquire.call_count == 6


def test_restarted_coordinator_has_no_location_snapshot(tmp_path):
    path = tmp_path/'restart.lock'
    clock = Clock()
    first = Coordinator(Mock(acquire=Mock(return_value=(row(),))), lease=HostLease(path),
                        monotonic=clock.mono, utcnow=clock.utc)
    first.request(); first.tick(); first.close()
    second = Coordinator(Mock(), lease=HostLease(path), monotonic=clock.mono, utcnow=clock.utc)
    try:
        assert second.peek() is None
        assert second.health()['wait'] == 30
        pending = second.request()
        assert not pending.done() and not second.tick()
    finally:
        second.close()


def test_cancellation_racing_publication_does_not_stop_authority(monkeypatch):
    central, _, _, transport = rig((row(),))
    pending = central.request()
    original = pending.done
    checks = [0]
    def racing_done():
        checks[0] += 1
        if checks[0] == 3:  # two expiry checks, then publication claims completion
            pending.cancel()
            return False
        return original()
    monkeypatch.setattr(pending, 'done', racing_done)
    assert central.tick()
    assert pending.cancelled() and not central.closed
    assert central.peek().version == 1


def test_pending_watch_cancelled_during_projection_cannot_create_late_watch(monkeypatch):
    central, source, clock, _ = rig((row(),))
    manager = WatchManager(Mock())
    fleet = FleetPolling(lambda: source, manager, autostart=False)
    fleet.request_watch('owner', 'TEST1', 'owner')
    central.tick()
    entered, release = Event(), Event()
    original = SnapshotSource.get_vehicles
    def project(self, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(self, **kwargs)
    monkeypatch.setattr(SnapshotSource, 'get_vehicles', project)
    thread = Thread(target=fleet.cycle)
    thread.start()
    try:
        assert entered.wait(3)
        fleet.cancel_pending('owner')
    finally:
        release.set(); thread.join(3)
    assert not manager.list_watches('owner')


def test_aware_utc_gps_is_projected_to_naive_bogota_with_correct_age():
    from test_widetech_official import payload
    result = parse_render_excel(payload([{'FechaGPS': '2026-01-01 05:00:00',
                                         'fltName': 'Ambulancias Medellin'}]), timezone_name='UTC')
    central, _, clock, _ = rig(result)
    source = SnapshotSource(central, LabelMapping('VEH_NAM', 'Movil'))
    central.request(); assert central.tick()
    vehicle = source.get_vehicles()[0]
    assert vehicle.gps_timestamp == datetime(2026, 1, 1)
    assert central.peek().records[0].gps_timestamp == datetime(2026, 1, 1, 5, tzinfo=timezone.utc)
    report = get_vehicle_location_by_id(source, vehicle.vehid, now=lambda: datetime(2026, 1, 1, 0, 6))
    assert report.report_age == 360 and report.stale
