"""Offline regression of per-row publication and explicit process state."""
from unittest.mock import Mock
import subprocess
import sys

import pytest

from gps_emi.acquisition import LabelMapping, SnapshotSource
from gps_emi.acquisition_runtime import HostLease, AuthorityBusy
from gps_emi.providers.widetech_official import parse_render_excel
from gps_emi.queries import get_vehicle_location_by_id
from gps_emi.monitoring.fleet_polling import FleetPolling
from gps_emi.monitoring.watches import WatchManager
from test_central_acquisition import rig
from test_widetech_official import payload


def batch(*rows):
    return parse_render_excel(payload([dict(fltName='Ambulancias Medellin', **r) for r in rows]))


@pytest.mark.parametrize('bad', [
    {'fltName': 'ABSENT'}, {'fltName': 'Otra', 'Velocidad': 'invalid'},
])
def test_valid_rows_update_alongside_unusable_rows(bad):
    first = batch({'VEH_ID': 'a'})
    second = parse_render_excel(payload([
        {'VEH_ID': 'a', 'fltName': 'Ambulancias Medellin', 'Latitude': '7'},
        dict(VEH_ID='b', **bad)]))
    central, _, clock, transport = rig(first, second)
    source = SnapshotSource(central, LabelMapping('VEH_NAM', 'Movil'))
    central.demand('test', True); assert central.tick()
    clock.advance(30); assert central.tick()
    assert source.get_vehicles()[0].latitude == 7
    assert len(central.peek().records) == 2
    assert len(central.peek().usable_records) == 1
    assert central.health()['received_rows'] == 2
    assert central.health()['usable_rows'] == 1
    assert central.peek().coverage == 'unknown'
    assert central.peek().diagnostics


@pytest.mark.parametrize('changes', [
    {'Latitude': 'invalid'}, {'Zones': 'ABSENT'}, {'Zones': None},
    {'Velocidad': 'invalid'}, {'fltName': 'ABSENT'}, {'duplicate': True},
])
def test_retained_origin_and_no_new_observation(changes):
    first = batch({'VEH_ID': 'a'})
    rows = [{'VEH_ID': 'a', 'fltName': 'Ambulancias Medellin', **changes}]
    if rows[0].pop('duplicate', False):
        rows.append(dict(rows[0], Latitude='8'))
    central, _, clock, transport = rig(first, parse_render_excel(payload(rows)))
    source = SnapshotSource(central, LabelMapping('VEH_NAM', 'Movil'))
    collector = Mock(active=True)
    manager = WatchManager(Mock())
    process = Mock(wraps=manager.process_snapshot)
    manager.process_snapshot = process
    fleet = FleetPolling(lambda: source, manager, collector=collector, autostart=False)
    fleet.request_watch('owner', 'SYNTHETIC-LABEL-A', 'target')
    assert central.tick()
    fleet.cycle()
    assert manager.active_count() == 1
    original = central.peek().operational[0]
    clock.advance(30); assert central.tick()
    fleet.cycle()
    assert process.call_args.args[0] == []
    assert manager.active_count() == 1
    retained, = central.peek().operational
    assert retained.record is original.record
    assert (retained.epoch, retained.version, retained.acquired_at, retained.source) == (
        original.epoch, original.version, original.acquired_at, original.source)
    assert source.get_vehicles(include_retained=False) == []
    assert collector.submit.call_args.args[0] == []
    report = get_vehicle_location_by_id(source, 'a')
    assert report.acquisition.retained and report.acquisition.age_seconds == 30
    assert central.health()['retained_records'] == 1
    for _ in range(5):
        source.get_vehicles(); get_vehicle_location_by_id(source, 'a'); fleet.cycle()
    assert transport.acquire.call_count == collector.submit.call_count == 2
    fleet.close()


@pytest.mark.parametrize('xml', [b'<DataTable>', b'<unrelated/>'])
def test_global_xml_failure_preserves_publication(xml):
    central, _, clock, transport = rig(batch({'VEH_ID': 'a'}))
    central.demand('test', True); central.tick()
    original = central.peek()
    transport.acquire.side_effect = lambda: parse_render_excel(xml)
    clock.advance(30); assert not central.tick()
    assert central.peek() is original


def test_missing_rows_do_not_confirm_disappearance():
    central, _, clock, _ = rig(batch({'VEH_ID': 'a'}), batch())
    central.demand('test', True); central.tick()
    clock.advance(30); assert central.tick()
    assert not central.peek().records and not central.peek().usable_records
    assert central.peek().operational[0].retained_reason == 'not_received'


def test_permission_failure_does_not_fall_back(monkeypatch, tmp_path):
    import builtins
    opener = Mock(side_effect=PermissionError())
    monkeypatch.setattr(builtins, 'open', opener)
    with pytest.raises(AuthorityBusy):
        HostLease(tmp_path/'state'/'acquisition.lock')
    assert opener.call_count == 1


def test_corrupt_state_fails_closed(tmp_path):
    path = tmp_path/'acquisition.lock'
    path.write_bytes(b' corrupt')
    with pytest.raises(AuthorityBusy):
        HostLease(path)
    assert path.read_bytes() == b' corrupt'


def test_configured_directory_across_processes_and_cwds(monkeypatch, tmp_path):
    # Subprocesses bypass conftest's isolated default_lock_path override.
    directory = tmp_path/'state'
    directory.mkdir()
    monkeypatch.setenv('GPS_EMI_STATE_DIR', str(directory))
    code = '''
from gps_emi.acquisition_runtime import default_lock_path, HostLease, AuthorityBusy
try:
    lease = HostLease(default_lock_path())
except AuthorityBusy:
    raise SystemExit(23)
lease.close()
'''
    with_lock = HostLease(directory/'acquisition.lock')
    try:
        for cwd in (tmp_path, directory):
            child = subprocess.run([sys.executable, '-c', code], cwd=cwd, capture_output=True, timeout=10)
            assert child.returncode == 23
    finally:
        with_lock.close()
    child = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, capture_output=True, timeout=10)
    assert child.returncode == 0
