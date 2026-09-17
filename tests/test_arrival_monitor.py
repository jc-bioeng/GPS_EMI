import pytest

from gps_emi.models import Vehicle
from gps_emi.monitoring.arrival import ArrivalMonitor, DESTINATIONS, MonitorState


@pytest.mark.parametrize("sequence,count,state", [
    ([False], 0, "OUTSIDE"),
    ([False, False], 0, "OUTSIDE"),
    ([False, True], 1, "ARRIVAL_DETECTED"),
    ([True], 0, "INSIDE"),
    ([True, True], 0, "INSIDE"),
    ([True, False, True], 1, "ARRIVAL_DETECTED"),
    ([False, True, True, False, True], 1, "ARRIVAL_DETECTED"),
])
def test_transitions(sequence, count, state):
    monitor = ArrivalMonitor(" amb-106 ", DESTINATIONS[0])
    assert monitor.state == MonitorState.INITIAL
    events = [monitor.observe(Vehicle("1", "AMB-106", zones=[DESTINATIONS[0]] if inside else []))
              for inside in sequence]
    assert sum(event is not None for event in events) == count
    assert monitor.state.value == state
    for event in filter(None, events):
        assert event.event_type == "ARRIVAL_DETECTED"
        assert event.vehicle.plate == "AMB-106"
        assert event.destination == DESTINATIONS[0]


@pytest.mark.parametrize("destination,zones,state", [
    (DESTINATIONS[0], ["ZONA 2 - POBLADO"], "OUTSIDE"),
    (DESTINATIONS[0], [DESTINATIONS[0]], "INSIDE"),
    (DESTINATIONS[1], ["ZONA 2 - POBLADO", DESTINATIONS[1]], "INSIDE"),
    (DESTINATIONS[0], [DESTINATIONS[0] + " extra"], "OUTSIDE"),
])
def test_exact_zone(destination, zones, state):
    monitor = ArrivalMonitor("AMB-106", destination)
    assert monitor.observe(Vehicle("1", "AMB-106", zones=zones)) is None
    assert monitor.state.value == state


def test_other_vehicle_cannot_change_state():
    monitor = ArrivalMonitor("AMB-106", DESTINATIONS[0])
    with pytest.raises(ValueError):
        monitor.observe(Vehicle("2", "AMB-999"))
    assert monitor.state == MonitorState.INITIAL


@pytest.mark.parametrize("plate,destination", [("", DESTINATIONS[0]), ("AMB-106", "ZONA 2 - POBLADO")])
def test_invalid_selection(plate, destination):
    with pytest.raises(ValueError):
        ArrivalMonitor(plate, destination)
