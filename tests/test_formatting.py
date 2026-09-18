from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from gps_emi.formatting import format_age, format_ignition, format_location, format_site_inventory
from gps_emi.models import Vehicle
from gps_emi.monitoring.observation import ObservationAssessment, ObservationStatus
from gps_emi.queries import get_vehicle_location, list_vehicles_at_site, LocationResult, SiteResult
from gps_emi.sites import EMI_SITES

NOW = datetime(2026, 9, 17, 12, 35)


@pytest.mark.parametrize('seconds,expected', [
    (43, 'hace 43 s'), (125, 'hace 2 min'), (786, 'hace 13 min'), (7200, 'hace 2 h'),
    (0, 'hace 0 s'), (59.9, 'hace 59 s'), (60, 'hace 1 min'), (3600, 'hace 1 h'),
    (None, 'N/D'), (-1, 'fecha futura (revisar reloj)'), (float('nan'), 'N/D'),
])
def test_human_age(seconds, expected):
    assert format_age(seconds) == expected


@pytest.mark.parametrize('value,expected', [
    (1, 'Encendida'), (True, 'Encendida'), ('1', 'Encendida'),
    (0, 'Apagada'), (False, 'Apagada'), ('0', 'Apagada'),
    (None, 'N/D'), (2, 'N/D'), ('unknown', 'N/D'),
])
def test_conservative_ignition(value, expected):
    assert format_ignition(value) == expected


@pytest.mark.parametrize('speed,expected', [(0, '0 km/h — Detenida'),
                                         (37, '37 km/h — En movimiento'), (None, 'N/D')])
def test_location_fields_and_original_address_even_inside_site(speed, expected):
    client = Mock()
    client.get_vehicles.return_value = [Vehicle(
        '433909', 'PJU886', NOW - timedelta(seconds=43), location='<b>COL - RIONEGRO</b>',
        speed=speed, ignition=0, gps_fix=1, mobile_number='AMB-20', zones=[EMI_SITES[0]],
    )]
    result = get_vehicle_location(client, 'AMB-20', now=lambda: NOW)
    output = format_location(result)
    for fragment in ['AMB-20', 'PJU886', '<b>COL - RIONEGRO</b>', '2026-09-17 12:34:17',
                     'hace 43 s', f'Velocidad: {expected}', 'Ignición: Apagada', 'GPSFix: 1']:
        assert fragment in output
    assert EMI_SITES[0] not in output
    assert 'Última posición reportada' in output
    assert 'STALE' not in output
    assert 'latitud' not in output.lower() and 'longitud' not in output.lower()


def test_stale_and_gpsfix_zero_keep_location_visible():
    client = Mock()
    client.get_vehicles.return_value = [Vehicle('1', 'PJU886', NOW - timedelta(seconds=786),
                                               location='Dirección reportada', gps_fix=0)]
    output = format_location(get_vehicle_location(client, 'PJU886', now=lambda: NOW))
    assert 'STALE' in output and 'hace 13 min' in output
    assert 'ADVERTENCIA: GPSFix=0' in output
    assert 'Dirección reportada' in output


def test_all_missing_values_format_safely():
    result = LocationResult(Vehicle('', ''), NOW,
                            ObservationAssessment(ObservationStatus.MISSING_TIMESTAMP), None)
    output = format_location(result)
    for label in ['Número de móvil', 'Placa', 'Hora GPS', 'Antigüedad del reporte',
                  'Estado del reporte', 'Velocidad', 'Ignición', 'GPSFix']:
        assert f'{label}: N/D' in output
    assert 'Última posición reportada:\nN/D' in output


def test_inventory_format_labels_stale_without_hiding_it():
    site = EMI_SITES[0]
    client = Mock()
    client.get_vehicles.return_value = [
        Vehicle('1', 'PJU886', NOW - timedelta(hours=2), speed=0, mobile_number='AMB-20', zones=[site]),
        Vehicle('2', '', speed=None, zones=[site]),
    ]
    result = list_vehicles_at_site(client, site, now=lambda: NOW)
    output = format_site_inventory(result)
    assert 'última posición reportada pertenece a esta geocerca' in output
    assert 'no garantiza presencia física actual' in output
    assert 'AMB-20' in output and 'PJU886' in output
    assert 'STALE — hace 2 h' in output and 'Detenida' in output
    assert 'N/D' in output
    assert 'latitud' not in output.lower() and 'longitud' not in output.lower()


def test_empty_site_inventory():
    output = format_site_inventory(SiteResult(EMI_SITES[0], NOW, ()))
    assert 'No hay ambulancias reportadas' in output
