from dataclasses import replace
from datetime import datetime, timedelta
from threading import Event
from unittest.mock import Mock

import pytest

from gps_emi.models import Vehicle, ArrivalEvent
from gps_emi.errors import TransientAcquisitionError, SessionExpiredError
from gps_emi.monitoring.arrival import MonitorState
from gps_emi.monitoring.runner import WatchRunner
from gps_emi.queries import get_vehicle_location, list_vehicles_at_site
from gps_emi.sites import EMI_SITES
from gps_emi.whatsapp.formatting import format_location, format_site
from gps_emi.whatsapp.notifier import WhatsAppNotifier
from gps_emi.whatsapp.service import WatchManager, MessageService
from gps_emi.whatsapp.worker import Inbox
from gps_emi.whatsapp.webhook import create_app
from gps_emi.whatsapp.client import WhatsAppError

BASE = datetime(2026, 9, 17, 12, 30)
NUMBER = '15555550101'


def vehicle(seconds=0, inside=False):
    return Vehicle('433909', 'PJU886', BASE + timedelta(seconds=seconds), location='Dirección original',
                   speed=0, ignition=1, gps_fix=1, mobile_number='AMB-20', zones=[EMI_SITES[0]] if inside else [])


@pytest.mark.parametrize('speed,expected', [(0, 'Detenida'), (37, 'En movimiento'), (None, 'N/D')])
@pytest.mark.parametrize('age,stale', [(43, False), (300, False), (301, True), (7200, True)])
def test_location_format_reuses_i3(speed, expected, age, stale):
    source = Mock()
    source.get_vehicles.return_value = [replace(vehicle(), speed=speed)]
    result = get_vehicle_location(source, 'AMB-20', now=lambda: BASE + timedelta(seconds=age))
    text = format_location(result)
    assert expected in text and 'STALE' not in text
    assert result.stale is stale
    assert ('⚠️' in text) == stale
    assert 'AMB-20' in text and 'PJU886' in text and 'Dirección original' in text
    assert 'Hora GPS:' in text and 'Ignición: Encendida' in text
    assert 'latitud' not in text.lower() and 'longitud' not in text.lower()
    assert 'no garantiza' in text


def test_missing_fields_and_fix_zero():
    source = Mock()
    source.get_vehicles.return_value = [Vehicle('1', '', gps_fix=0, mobile_number='MOVIL- 96')]
    result = get_vehicle_location(source, 'MOVIL- 96', now=lambda: BASE)
    text = format_location(result)
    assert 'MOVIL- 96' in text and 'AMB-96' not in text
    assert 'Placa: N/D' in text and 'GPSFix=0' in text
    assert 'Hora GPS: N/D' in text and '\nN/D\n' in text
    source.get_vehicles.return_value = [Vehicle('1', 'PJU886')]
    assert 'Móvil: N/D' in format_location(get_vehicle_location(source, 'PJU886', now=lambda: BASE))


def test_inventory_reuses_order_and_conservative_freshness():
    source = Mock()
    source.get_vehicles.return_value = [replace(vehicle(0, True), mobile_number='OLD'),
        replace(vehicle(560, True), mobile_number='FRESH'),
        replace(vehicle(0, True), gps_timestamp=None, mobile_number='UNKNOWN')]
    result = list_vehicles_at_site(source, EMI_SITES[0], now=lambda: BASE + timedelta(seconds=600))
    text = format_site(result)
    assert text.index('FRESH') < text.index('OLD') < text.index('UNKNOWN')
    assert '🟢 Hace 40 s' in text and '⚠️ Hace 10 min' in text and '❔' in text
    assert 'STALE' not in text
    assert [entry.stale for entry in result.entries] == [False, True, None]
    assert 'última posición reportada' in text and 'no garantiza' in text
    assert 'latitud' not in text.lower() and 'longitud' not in text.lower()
    source.get_vehicles.return_value = []
    assert 'No hay ambulancias' in format_site(list_vehicles_at_site(source, EMI_SITES[0], now=lambda: BASE))


def test_template_notifier_and_dedup(wa_config, messenger):
    notifier = WhatsAppNotifier(NUMBER, messenger, wa_config)
    event = ArrivalEvent(vehicle(60, True), EMI_SITES[0])
    notifier.send_arrival(event)
    notifier.send_arrival(event)
    messenger.client.send_template.assert_called_once_with(NUMBER, wa_config.template_name, 'es',
        ['AMB-20', 'PJU886', EMI_SITES[0], str(event.vehicle.gps_timestamp)])
    messenger.client.send_text.assert_not_called()
    assert notifier.accepted and notifier.last_event is event


def test_ambiguous_template_suppressed_but_text_conservative(wa_config, messenger):
    event = ArrivalEvent(vehicle(), ' / '.join(EMI_SITES), sites=EMI_SITES)
    notifier = WhatsAppNotifier(NUMBER, messenger, wa_config)
    notifier.send_arrival(event)
    assert notifier.delivery_error == 'ambiguous_arrival_site'
    messenger.client.send_template.assert_not_called()
    messenger.windows.note(NUMBER, 1000000)
    notifier = WhatsAppNotifier(NUMBER, messenger, replace(wa_config, arrival_mode='text'))
    notifier.send_arrival(event)
    text = messenger.client.send_text.call_args.args[1]
    assert 'sin sede única' in text and all(site in text for site in EMI_SITES)


def test_text_arrival_outside_window_retains_event(wa_config, messenger):
    notifier = WhatsAppNotifier(NUMBER, messenger, replace(wa_config, arrival_mode='text'))
    notifier.send_arrival(ArrivalEvent(vehicle(), EMI_SITES[0]))
    assert notifier.delivery_error == 'service_window_closed'
    assert notifier.last_event is not None and not notifier.accepted
    messenger.client.send_text.assert_not_called()


@pytest.mark.parametrize('identifier', ['AMB-20', 'PJU886'])
def test_runner_confirmation_recovery_and_arrival_send_failure_keeps_state(wa_config, messenger, identifier):
    messenger.client.send_template.side_effect = WhatsAppError('timeout')
    source = Mock()
    source.get_vehicles.side_effect = [[vehicle()], TransientAcquisitionError(),
                                     [vehicle(-1, True)], [vehicle(0, True)], [vehicle(60, True)]]
    notifier = WhatsAppNotifier(NUMBER, messenger, wa_config)
    confirmed, sleep = Mock(), Mock()
    runner = WatchRunner(source, identifier, None, notifier, sleep=sleep,
                         now=lambda: BASE + timedelta(minutes=5), on_resolved=confirmed)
    assert runner.run() == 0
    confirmed.assert_called_once_with(vehicle())
    assert runner.vehid == '433909' and runner.monitor.state == MonitorState.ARRIVAL_DETECTED
    assert runner.validator.last_processed_gps_timestamp == BASE + timedelta(seconds=60)
    assert notifier.delivery_error == 'timeout' and notifier.last_event.site == EMI_SITES[0]
    assert runner.run() == 0
    messenger.client.send_template.assert_called_once()


@pytest.mark.parametrize('phase', ['before', 'request', 'polling', 'backoff'])
def test_runner_cooperative_shutdown(phase):
    stop = Mock()
    stop.is_set.side_effect = [True] if phase == 'before' else [False, True] if phase == 'request' else [False, False]
    stop.wait.return_value = True
    source = Mock()
    source.get_vehicles.side_effect = TransientAcquisitionError() if phase == 'backoff' else None
    source.get_vehicles.return_value = [vehicle()]
    notifier = Mock()
    runner = WatchRunner(source, 'AMB-20', None, notifier, stop_event=stop)
    assert runner.run() == 130
    notifier.send_arrival.assert_not_called()
    if phase == 'before':
        source.get_vehicles.assert_not_called()


def test_manager_accepts_pending_watches_during_acquisition(wa_config, messenger):
    messenger.windows.note(NUMBER, 1000000)
    started, release = Event(), Event()
    source = Mock()
    def acquire():
        started.set()
        assert release.wait(timeout=2)
        return [vehicle()]
    source.get_vehicles.side_effect = acquire
    manager = WatchManager(lambda: source, messenger, wa_config)
    assert manager.start(NUMBER, 'AMB-20')
    try:
        assert started.wait(timeout=1)
        assert manager.start(NUMBER, 'PJU886')
        assert manager.active
    finally:
        manager.stop_event.set()
        release.set()
        assert manager.close(timeout=1)
    assert not manager.active and not manager.start(NUMBER, 'AMB-20')


def test_webhook_returns_while_watch_is_blocked(wa_config, messenger):
    # Ningún tiempo real de polling: el reloj está fijado y se sincroniza por eventos.
    from test_webhook import payload, post
    started, release = Event(), Event()
    source = Mock()
    def acquire():
        started.set()
        assert release.wait(timeout=2)
        return [vehicle()]
    source.get_vehicles.side_effect = acquire
    manager = WatchManager(lambda: source, messenger, wa_config)
    service = MessageService(wa_config, messenger, manager, lambda: source)
    inbox = Inbox(service.handle, now=lambda: 0)
    client = create_app(wa_config, inbox).test_client()
    try:
        assert post(client, wa_config, payload(wa_config, text='VIGILAR AMB-20')).status_code == 200
        assert inbox.process_one()
        assert started.wait(timeout=1)
        assert post(client, wa_config, payload(wa_config, identifier='menu')).status_code == 200
        assert inbox.process_one()
        messenger.client.send_menu.assert_called_once_with(NUMBER)
        assert manager.active
    finally:
        manager.stop_event.set()
        release.set()
        manager.close(timeout=1)
        inbox.close(timeout=0)


@pytest.mark.parametrize('rows,expected', [([], 'No encontré'),
    ([vehicle(), vehicle()], 'ambiguo')])
def test_manager_reports_resolution_error_without_false_start(wa_config, messenger, rows, expected):
    messenger.windows.note(NUMBER, 1000000)
    source = Mock()
    source.get_vehicles.return_value = rows
    manager = WatchManager(lambda: source, messenger, wa_config)
    manager.start(NUMBER, 'AMB-20')
    manager.thread.join(timeout=1)
    assert not manager.active
    assert expected in messenger.client.send_text.call_args.args[1]
    assert 'Vigilancia iniciada' not in messenger.client.send_text.call_args.args[1]
    manager.close(timeout=0)


@pytest.mark.parametrize('identifier', ['AMB-20', 'PJU886'])
@pytest.mark.parametrize('confirmation_fails', [False, True])
def test_manager_shared_polling_confirmation_then_arrival(wa_config, messenger, identifier, confirmation_fails):
    messenger.windows.note(NUMBER, 1000000)
    if confirmation_fails:
        messenger.client.send_text.side_effect = WhatsAppError('connection')
    source = Mock()
    source.get_vehicles.side_effect = [[vehicle()], [vehicle(60, True)]]
    manager = WatchManager(lambda: source, messenger, wa_config, autostart=False)
    try:
        assert manager.start(NUMBER, identifier)
        manager.polling.cycle()
        manager.polling.cycle()
        assert not manager.active
        watch, = manager.manager.list_watches(NUMBER)
        assert watch.monitor.state == MonitorState.ARRIVAL_DETECTED
        text = messenger.client.send_text.call_args.args[1]
        assert 'Vigilancia iniciada' in text and 'AMB-20' in text and 'PJU886' in text
        messenger.client.send_template.assert_called_once()
        assert watch.notification_status == 'accepted'
        assert source.get_vehicles.call_count == 2  # Sin consulta de preflight adicional.
    finally:
        manager.close(timeout=0)


def test_thread_start_failure_releases_slot(wa_config, messenger):
    thread = Mock()
    thread.start.side_effect = RuntimeError('synthetic failure')
    manager = WatchManager(Mock(), messenger, wa_config, thread_factory=Mock(return_value=thread))
    with pytest.raises(RuntimeError):
        manager.start(NUMBER, 'AMB-20')
    assert not manager.active


def test_accepted_watch_can_be_followed_by_new_watch(wa_config, messenger):
    source = Mock()
    source.get_vehicles.return_value = []
    messenger.windows.note(NUMBER, 1000000)
    manager = WatchManager(lambda: source, messenger, wa_config)
    try:
        for _ in range(2):
            assert manager.start(NUMBER, 'AMB-20')
            manager.thread.join(timeout=1)
            assert not manager.active
        assert source.get_vehicles.call_count == 2
    finally:
        manager.close(timeout=0)
