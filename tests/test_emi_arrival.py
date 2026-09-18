from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from gps_emi.errors import SessionExpiredError, TransientAcquisitionError
from gps_emi.models import Vehicle
from gps_emi.monitoring.arrival import ArrivalMonitor, MonitorState
from gps_emi.monitoring.runner import WatchRunner, watch_arrival
from gps_emi.sites import EMI_SITES, matching_sites

POBLADO, TALLER = EMI_SITES
BASE = datetime(2026, 9, 17, 12, 30)


def vehicle(site=None, seconds=0):
    return Vehicle('433909', 'PJU886', gps_timestamp=BASE + timedelta(seconds=seconds),
                   mobile_number='AMB-20', gps_fix=1, zones=[site] if site else [])


@pytest.mark.parametrize('sequence,expected_state,expected_site', [
    ([POBLADO], MonitorState.INSIDE_EMI, None),
    ([TALLER], MonitorState.INSIDE_EMI, None),
    ([None, POBLADO], MonitorState.ARRIVAL_DETECTED, POBLADO),
    ([None, TALLER], MonitorState.ARRIVAL_DETECTED, TALLER),
    ([TALLER, POBLADO], MonitorState.INSIDE_EMI, None),
    ([POBLADO, TALLER], MonitorState.INSIDE_EMI, None),
    ([TALLER, None, POBLADO], MonitorState.ARRIVAL_DETECTED, POBLADO),
    ([POBLADO, None, TALLER], MonitorState.ARRIVAL_DETECTED, TALLER),
    (['ZONA 2 - POBLADO'], MonitorState.OUTSIDE_EMI, None),
    ([None, None], MonitorState.OUTSIDE_EMI, None),
])
def test_union_arrival_sequences(sequence, expected_state, expected_site):
    monitor = ArrivalMonitor('PJU886')
    events = [monitor.observe(vehicle(site)) for site in sequence]
    events = [event for event in events if event is not None]
    assert monitor.state == expected_state
    assert len(events) == (1 if expected_site else 0)
    if expected_site:
        assert events[0].site == expected_site
        assert events[0].destination == expected_site
        assert events[0].sites == (expected_site,)
        assert monitor.observe(vehicle()) is None
        assert monitor.observe(vehicle(expected_site)) is None
    if sequence[-1] in EMI_SITES:
        assert monitor.actual_site == sequence[-1]


def test_general_poblado_zone_does_not_hide_exact_site():
    monitor = ArrivalMonitor('PJU886')
    observation = replace(vehicle(POBLADO), zones=['ZONA 2 - POBLADO', POBLADO])
    assert monitor.observe(observation) is None
    assert monitor.state == MonitorState.INSIDE_EMI
    assert monitor.actual_site == POBLADO


def test_both_sites_are_preserved_without_inventing_single_site():
    monitor = ArrivalMonitor('PJU886')
    assert monitor.observe(vehicle()) is None
    event = monitor.observe(replace(vehicle(), zones=[TALLER, POBLADO]))
    assert event.site is None
    assert event.sites == EMI_SITES
    assert monitor.actual_site is None
    assert monitor.actual_sites == EMI_SITES
    assert POBLADO in event.destination and TALLER in event.destination


def test_site_lookup_is_exact_and_independent_of_zone_order():
    assert matching_sites(iter([TALLER, POBLADO])) == EMI_SITES
    assert matching_sites(['ZONA 2 - POBLADO', POBLADO.lower(), TALLER + ' extra']) == ()


@pytest.mark.parametrize('site', EMI_SITES)
def test_emi_runner_preserves_i2_recovery_and_temporal_validation(site, caplog):
    client, notifier, sleep = Mock(), Mock(), Mock()
    client.get_vehicles.side_effect = [
        [vehicle()], TransientAcquisitionError(), [vehicle(site, -60)],
        [vehicle(site, 0)], [], [vehicle(site, 60)],
    ]
    runner = WatchRunner(client, 'AMB-20', None, notifier, sleep=sleep, now=lambda: BASE + timedelta(minutes=5))
    assert runner.run() == 0
    assert runner.run() == 0
    notifier.send_arrival.assert_called_once()
    event = notifier.send_arrival.call_args.args[0]
    assert event.site == site
    assert event.vehicle.gps_timestamp == BASE + timedelta(minutes=1)
    assert client.get_vehicles.call_count == 6
    assert [call.args[0] for call in sleep.call_args_list] == [30, 5, 30, 30, 5]
    assert 'OUT_OF_ORDER' in caplog.text
    assert 'Adquisición recuperada' in caplog.text
    assert 'OUTSIDE_EMI' in caplog.text and 'INSIDE_EMI' in caplog.text


@pytest.mark.parametrize('start,end', [(POBLADO, TALLER), (TALLER, POBLADO)])
def test_watch_use_case_between_sites_never_notifies(start, end):
    client, notifier = Mock(), Mock()
    client.get_vehicles.side_effect = [[vehicle(start)], [vehicle(end, 60)], SessionExpiredError()]
    assert watch_arrival(client, 'PJU886', notifier, sleep=Mock(), now=lambda: BASE) == 1
    notifier.send_arrival.assert_not_called()


def test_legacy_destination_remains_explicitly_supported():
    monitor = ArrivalMonitor('PJU886', POBLADO)
    assert monitor.observe(vehicle(TALLER)) is None
    assert monitor.state == MonitorState.OUTSIDE
    assert monitor.observe(vehicle(POBLADO)).site == POBLADO
