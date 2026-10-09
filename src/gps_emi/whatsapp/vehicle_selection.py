"""Presentación Meta de candidatos; nunca decide cuál vehículo escoger."""
from collections import Counter
from gps_emi.config import WatchConfig
from gps_emi.monitoring import runner
from gps_emi.queries import describe_vehicle
from gps_emi.selection import SelectionError
from .formatting import display, display_location, freshness

PAGE_SIZE = 8  # Reserva dos filas para navegación dentro del límite de diez.


def selection_payload(context, config=None, page=0):
    total = (len(context.candidates) + PAGE_SIZE - 1) // PAGE_SIZE
    if not 0 <= page < total:
        raise ValueError('Página no disponible.')
    rows = []
    now = runner.local_now()
    for token, vehicle, report in zip(context.choice_ids, context.candidates, context.candidate_reports):
        conserved = 'Conservado · ' if report.acquisition and report.acquisition.retained else ''
        description = conserved + f'{display(vehicle.plate)} · {freshness(describe_vehicle(vehicle, now, config or WatchConfig()))} · {display_location(vehicle.location)}'
        rows.append({'id': f'vehicle_select:{context.selection_id}:{token}',
                     'title': (vehicle.mobile_number or vehicle.plate or 'Registro')[:24],
                     'description': description.replace('\n', ' ')[:72]})
    duplicates = Counter((r['title'], r['description']) for r in rows)
    for row, vehicle, report in zip(rows, context.candidates, context.candidate_reports):
        if duplicates[row['title'], row['description']] > 1:
            conserved = 'Conservado · ' if report.acquisition and report.acquisition.retained else ''
            row['description'] = (conserved + f'GPS: {display(vehicle.gps_timestamp)} · Fix: {display(vehicle.gps_fix)}'
                                  f' · Vel: {display(vehicle.speed)} · Ign: {display(vehicle.ignition)}')[:72]
    duplicates = Counter((r['title'], r['description']) for r in rows)
    for row, vehicle, report in zip(rows, context.candidates, context.candidate_reports):
        if duplicates[row['title'], row['description']] > 1:
            # Último recurso: los datos visibles disponibles no distinguen registros.
            conserved = 'Conservado · ' if report.acquisition and report.acquisition.retained else ''
            row['description'] = (conserved + 'Registro: ' + vehicle.vehid)[:72]
    if len({(r['title'], r['description']) for r in rows}) != len(rows):
        raise SelectionError('unavailable')
    page_rows = rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    if page:
        page_rows.append({'id': f'vehicle_page:{context.selection_id}:{page-1}', 'title': 'Anterior'})
    if page + 1 < total:
        page_rows.append({'id': f'vehicle_page:{context.selection_id}:{page+1}', 'title': 'Siguiente'})
    return {'type': 'list', 'header': {'type': 'text', 'text': 'Seleccionar móvil'},
            'body': {'text': f'⚠️ Encontré varios registros para {context.original_identifier[:100]}.\n\nSelecciona el móvil correcto para continuar.\nPágina {page+1} de {total}. Válida durante 5 minutos desde la primera lista.'},
            'footer': {'text': 'MENU o CANCELAR cancela esta selección.'},
            'action': {'button': 'Seleccionar', 'sections': [{'title': 'Registros', 'rows': page_rows}]}}
