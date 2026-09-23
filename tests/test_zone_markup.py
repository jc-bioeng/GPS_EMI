import json
from datetime import datetime
from unittest.mock import Mock

import pytest

from gps_emi.providers.widetech import WideTechClient, zone_list
from gps_emi.monitoring.watches import WatchManager, WatchStatus
from gps_emi.queries import list_vehicles_at_site
from gps_emi.sites import EMI_SITES


def fleet(monkeypatch, zones, second=0):
    # LoadDataLog simulado: parser real, normalización y filtro real de flota.
    payload = json.dumps({'Rows': [{'VEHID': 1, 'VEH_LCNS': 'AMB-20',
        'VEH_NAM': 'PJU886', 'Zones': zones, 'fltName': 'Ambulancias Medellin;44986;0',
        'Location': '<b>Dirección original</b>'}]}, ensure_ascii=False)
    payload = payload.replace('"VEHID": 1', f'"Fecha": new Date(2026,8,22,12,0,{second}), "VEHID": 1')
    monkeypatch.setattr(WideTechClient, 'load_data_log', lambda self: payload)
    return WideTechClient()


@pytest.mark.parametrize('site', EMI_SITES)
@pytest.mark.parametrize('wrapper', ['{<B>%s</B>}', '<B>{%s}</B>', '<B>%s</B>', '{%s}'])
def test_html_zones_reach_domain_and_inventory(monkeypatch, site, wrapper):
    client = fleet(monkeypatch, wrapper % site)
    vehicle, = client.get_vehicles()
    assert vehicle.zones == [site]
    assert vehicle.location == '<b>Dirección original</b>'
    result = list_vehicles_at_site(client, site, now=lambda: datetime(2026,9,22,12,1))
    assert [entry.vehicle.vehid for entry in result.entries] == ['1']
    other = next(s for s in EMI_SITES if s != site)
    assert not list_vehicles_at_site(client, other).entries


@pytest.mark.parametrize('site', EMI_SITES)
def test_markup_outside_inside_generates_one_arrival(monkeypatch, site):
    notify = Mock(return_value=True)
    manager = WatchManager(notify, now=lambda: datetime(2026,9,22,12,1))
    outside = fleet(monkeypatch, '{Otra zona}').get_vehicles()
    watch, _ = manager.create_watch('owner', outside[0], 'target')
    manager.process_snapshot(outside)
    inside = fleet(monkeypatch, '{<B>' + site + '</B>}', 1).get_vehicles()
    manager.process_snapshot(inside)
    manager.process_snapshot(inside)
    notify.assert_called_once()
    assert notify.call_args.args[1].site == site
    assert manager.get_watch('owner', watch.watch_id).status == WatchStatus.COMPLETED


@pytest.mark.parametrize('site', EMI_SITES)
def test_first_inside_and_old_reports_do_not_create_retroactive_arrival(monkeypatch, site):
    notify = Mock()
    manager = WatchManager(notify, now=lambda: datetime(2026,9,22,12,1))
    inside = fleet(monkeypatch, '{<B>' + site + '</B>}', 5).get_vehicles()
    watch, _ = manager.create_watch('owner', inside[0], 'target')
    manager.process_snapshot(inside)
    # Un exterior viejo o duplicado no puede crear una transición retrospectiva.
    manager.process_snapshot(fleet(monkeypatch, '{Otra zona}', 4).get_vehicles())
    manager.process_snapshot(fleet(monkeypatch, '{Otra zona}', 5).get_vehicles())
    other = next(s for s in EMI_SITES if s != site)
    manager.process_snapshot(fleet(monkeypatch, '{<B>' + other + '</B>}', 6).get_vehicles())
    notify.assert_not_called()
    assert manager.get_watch('owner', watch.watch_id).status == WatchStatus.ACTIVE


@pytest.mark.parametrize('raw,expected', [
    ('Z - {<span title="a > b"><b>EMI_Medellin_Taller</b></span>}; Z - {Otra zona}', ['EMI_Medellin_Taller', 'Otra zona']),
    ('{Zona &amp; clínica}', ['Zona & clínica']),
    ('{Zona válida - ÁREA_2}', ['Zona válida - ÁREA_2']),
    ('{ EMI_Medellin_Taller }', [' EMI_Medellin_Taller ']),
    ('<!-- {EMI_Medellin_Taller} --><script>{EMI_Medellin_Taller}</script><style>{Otra}</style>', []),
    ('{<b>EMI_Medellin_Taller anexo</b>}', ['EMI_Medellin_Taller anexo']),
    ('', []), (None, []),
])
def test_safe_text_extraction_preserves_names(raw, expected):
    assert zone_list(raw) == expected


def test_inventory_both_exact_sites_and_no_partial_match(monkeypatch):
    client = fleet(monkeypatch, '{<B>EMI Medellin_Poblado</B>}; {<i>EMI_Medellin_Taller</i>}')
    for site in EMI_SITES:
        assert len(list_vehicles_at_site(client, site).entries) == 1
    client = fleet(monkeypatch, '{<B>EMI_Medellin_Taller anexo</B>}; {emi medellin_poblado}')
    for site in EMI_SITES:
        assert not list_vehicles_at_site(client, site).entries
