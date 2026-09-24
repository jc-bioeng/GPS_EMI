from datetime import datetime

import pytest

from gps_emi.config import WatchConfig
from gps_emi.models import Vehicle
from gps_emi.queries import describe_vehicle
from gps_emi.selection import PendingSelections, SelectionOperation
from gps_emi.sites import EMI_SITES
from gps_emi.whatsapp.formatting import display_location, format_location
from gps_emi.whatsapp.vehicle_selection import selection_payload


@pytest.mark.parametrize('site', EMI_SITES)
def test_location_message_removes_markup_without_changing_vehicle(site):
    raw = f'<B>{site}</B>'
    vehicle = Vehicle('433909', 'PJU886', location=raw, mobile_number='AMB-20')
    result = describe_vehicle(vehicle, datetime(2026, 9, 24), WatchConfig())
    message = format_location(result)
    assert f'\n{site}\n' in message
    assert '<B>' not in message and '</B>' not in message
    assert vehicle.location == raw


@pytest.mark.parametrize('raw,expected', [
    ('<div><b>Calle 10</b><br>Medellín &amp; Poblado</div>', 'Calle 10\nMedellín & Poblado'),
    ('<!-- comentario --><B>Sede</B><script>oculto</script><style>oculto</style>', 'Sede'),
    ('Calle 10 # 20-30; A < 3 & B > 1', 'Calle 10 # 20-30; A < 3 & B > 1'),
    ('<b></b>', 'N/D'),
    (None, 'N/D'),
])
def test_location_visible_text(raw, expected):
    assert display_location(raw) == expected


def test_selection_removes_markup_before_truncating():
    raw = '<b class="' + 'x' * 100 + '">EMI_Medellin_Taller</b>'
    candidates = [Vehicle(str(i), f'PLATE{i}', location=raw, mobile_number=f'AMB-{i}')
                  for i in (1, 2)]
    selections = PendingSelections()
    generation = selections.begin('owner')
    context = selections.offer('owner', SelectionOperation.LOCATION, 'AMB', candidates,
                               'owner', generation)
    rows = selection_payload(context)['action']['sections'][0]['rows']
    assert all('EMI_Medellin_Taller' in row['description'] for row in rows)
    assert all('<' not in row['description'] for row in rows)
    assert all(len(row['description']) <= 72 for row in rows)
    assert all(vehicle.location == raw for vehicle in context.candidates)
