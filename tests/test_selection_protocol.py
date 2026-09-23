from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from threading import Barrier

import pytest

from gps_emi.models import Vehicle
from gps_emi.resolution import resolve_vehicle, find_vehicle, ResolutionStatus, AmbiguousVehicleError
from gps_emi.selection import PendingSelections, SelectionOperation, SelectionError


def candidates():
    return tuple(Vehicle(str(i), 'PRU332', datetime(2026,9,22,12)+timedelta(seconds=i),
                         mobile_number=name, location='Ubicación '+str(i), gps_fix=i)
                 for i,name in enumerate(('PRU332 DEMO','PRU332','PRU332-DEMO'),1))


@pytest.mark.parametrize('identifier,status,count', [('UNKNOWN',ResolutionStatus.NOT_FOUND,0),
    ('PRU332 DEMO',ResolutionStatus.RESOLVED,1),(' pru332 ',ResolutionStatus.AMBIGUOUS,3)])
def test_explicit_resolution_states(identifier,status,count):
    result = resolve_vehicle(candidates(),identifier)
    assert result.status == status and len(result.candidates) == count
    assert (result.vehicle is not None) == (status == ResolutionStatus.RESOLVED)


@pytest.mark.parametrize('order', [(0,1,2),(2,1,0),(1,2,0)])
def test_no_heuristics_and_fail_safe_preserved(order):
    original = candidates()
    rows = [original[i] for i in order]
    result = resolve_vehicle(rows,'PRU332')
    assert result.vehicle is None and result.candidates == tuple(rows)
    with pytest.raises(AmbiguousVehicleError) as error:
        find_vehicle(rows,'PRU332')
    assert error.value.candidates == tuple(rows)
    assert all(v.location and v.gps_timestamp is not None for v in result.candidates)


def offer(store,owner='A',operation=SelectionOperation.LOCATION):
    return store.offer(owner,operation,'PRU332',candidates(),'target-'+owner,store.begin(owner))


def test_consumption_returns_exact_identity_and_context():
    store = PendingSelections(now=lambda:10)
    context = offer(store,operation=SelectionOperation.CREATE_WATCH)
    selected,vehid = store.consume('A',context.selection_id,context.choice_ids[1])
    assert vehid == '2' and selected.owner_id == 'A'
    assert selected.notification_target == 'target-A'
    assert selected.operation == SelectionOperation.CREATE_WATCH
    assert selected.original_identifier == 'PRU332' and selected.created_at == 10
    assert selected.candidates == candidates()
    assert len(selected.candidate_reports) == 3
    assert all(report.report_age is not None and report.stale is not None for report in selected.candidate_reports)
    with pytest.raises(SelectionError):
        store.consume('A',context.selection_id,context.choice_ids[1])


@pytest.mark.parametrize('attack', ['owner','context','candidate'])
def test_reject_manipulation_without_consuming_valid_context(attack):
    store = PendingSelections()
    context = offer(store)
    with pytest.raises(SelectionError):
        store.consume('B' if attack=='owner' else 'A',
                      'wrong' if attack=='context' else context.selection_id,
                      'wrong' if attack=='candidate' else context.choice_ids[1])
    assert store.consume('A',context.selection_id,context.choice_ids[1])[1] == '2'


def test_expiration_and_late_offer_after_new_operation():
    clock = [0]
    store = PendingSelections(now=lambda:clock[0])
    context = offer(store)
    clock[0] = 300
    with pytest.raises(SelectionError,match='expired'):
        store.consume('A',context.selection_id,context.choice_ids[0])
    old = store.current('A')
    store.begin('A')
    assert store.offer('A',SelectionOperation.CREATE_WATCH,'PRU332',candidates(),'target',old) is None


def test_new_selection_rejects_old_even_for_same_vehid():
    store = PendingSelections()
    old,new = offer(store),offer(store)
    with pytest.raises(SelectionError):
        store.consume('A',old.selection_id,old.choice_ids[1])
    assert store.consume('A',new.selection_id,new.choice_ids[1])[1] == '2'


def test_atomic_consume_with_two_responses():
    store = PendingSelections()
    context = offer(store)
    barrier = Barrier(2)
    def consume(_):
        barrier.wait(timeout=2)
        try:
            return store.consume('A',context.selection_id,context.choice_ids[1])[1]
        except SelectionError:
            return None
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(consume,range(2)),key=lambda x:x or '') == [None,'2']


@pytest.mark.parametrize('rows', [(candidates()[0],candidates()[0]), (replace(candidates()[0],vehid=''),candidates()[1])])
def test_unusable_technical_identity_remains_fail_safe(rows):
    store = PendingSelections()
    with pytest.raises(SelectionError):
        store.offer('A',SelectionOperation.LOCATION,'PRU332',rows,'target',store.begin('A'))
