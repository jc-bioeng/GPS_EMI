"""The existing WhatsApp service consumes the national projection offline."""
from dataclasses import replace

from gps_emi.whatsapp.service import MessageService, WatchManager
from gps_emi.whatsapp.webhook import IncomingMessage
from test_phase3_catalog import rig, batch, record, step

NUMBER = '15555550101'


def test_national_query_selector_and_medellin_watch_only(tmp_path, wa_config, messenger):
    central, source, clock, store = rig(tmp_path,
        batch(record('a',VEH_NAM='SAME'),record('b',VEH_NAM='SAME',fltName='Ambulancias Cali')))
    config = replace(wa_config,allowed_numbers=frozenset({NUMBER}))
    watches = WatchManager(lambda:source,messenger,config,autostart=False)
    service = MessageService(config,messenger,watches,lambda:source)
    assert step(central,clock)
    service.handle(IncomingMessage('query',NUMBER,'UBICACION MOBILE-b',1000000))
    assert 'MOBILE-b' in messenger.client.send_text.call_args.args[1]
    service.handle(IncomingMessage('selection',NUMBER,'UBICACION SAME',1000000))
    assert len(service.vehicle_choices[NUMBER]) == 2
    service.handle(IncomingMessage('choice',NUMBER,'2',1000000))
    assert 'MOBILE-b' in messenger.client.send_text.call_args.args[1]
    service.handle(IncomingMessage('watch',NUMBER,'VIGILAR MOBILE-b',1000000))
    watches.polling.cycle()
    assert not watches.list_active(NUMBER)
    assert central.metrics['requests'] == 1
    watches.close()


def test_reclassification_does_not_send_proactive_whatsapp(tmp_path,wa_config,messenger):
    central, source, clock, store = rig(tmp_path,batch(record()),batch(record(fltName='Otra',FechaGPS='bad')))
    config = replace(wa_config,allowed_numbers=frozenset({NUMBER}))
    watches = WatchManager(lambda:source,messenger,config,autostart=False)
    service = MessageService(config,messenger,watches,lambda:source)
    step(central,clock)
    service.handle(IncomingMessage('watch',NUMBER,'VIGILAR TEST-A',1000000))
    watches.polling.cycle()
    assert len(watches.list_active(NUMBER)) == 1
    sent = messenger.client.send_text.call_count
    step(central,clock); watches.polling.cycle()
    assert not watches.list_active(NUMBER)
    assert watches.manager.list_watches(NUMBER)[0].failure_code == 'fleet_changed'
    assert messenger.client.send_text.call_count == sent
    watches.close()
