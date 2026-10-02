"""Control local de sesiones; nunca inicia consultas GPS ni carga .env."""
import argparse
from datetime import datetime
import os
import sqlite3
from gps_emi.analysis.collector import DEFAULT_DB
from gps_emi.analysis.sessions import SessionStore, duration_seconds
from gps_emi.analysis.export_observations import export_csv, timestamp
from gps_emi.clock import acquisition_now, BOGOTA
from gps_emi.observability import configure_logging


def main(argv=None):
    parser = argparse.ArgumentParser(description='GPS EMI — Data Collection')
    parser.add_argument('--db', default=os.environ.get('GPS_EMI_DATA_DB', DEFAULT_DB))
    commands = parser.add_subparsers(dest='action', required=True)
    start = commands.add_parser('start')
    start.add_argument('--duration', required=True)
    commands.add_parser('status')
    commands.add_parser('stop')
    export = commands.add_parser('export')
    export.add_argument('--session', required=True)
    export.add_argument('--output', required=True)
    export.add_argument('--from', dest='start', type=timestamp)
    export.add_argument('--to', dest='end', type=timestamp)
    args = parser.parse_args(argv)
    configure_logging()
    try:
        if args.action == 'export':
            count = export_csv(args.db, args.output, args.start, args.end, session_id=args.session)
            print(f'Observations exported: {count}')
            return 0
        store = SessionStore(args.db)
        if args.action == 'start':
            store.start_session(duration_seconds(args.duration))
        session = store.status(stop=args.action == 'stop')
        print('GPS EMI — Data Collection')
        if session is None:
            print('No existe sesión activa ni sesiones anteriores.')
        else:
            if session['status'] != 'COLLECTING':
                print('No existe sesión activa. Última sesión:')
            for label, field in [('Session', 'id'), ('Status', 'status'), ('Started', 'started_at'),
                                 ('Ends', 'planned_end_at'), ('Stopped', 'stopped_at'),
                                 ('Observations', 'observations'), ('Vehicles', 'vehicles')]:
                value = session[field]
                if field.endswith('_at') and value:
                    value = datetime.fromisoformat(value).astimezone(BOGOTA).isoformat()
                print(f'{label}: {value}')
            remaining = max(0, int((datetime.fromisoformat(session['planned_end_at']) - acquisition_now()).total_seconds())) if session['status'] == 'COLLECTING' else 0
            print(f'Remaining: {remaining // 3600}h {(remaining % 3600) // 60}m')
        print(f'Database: {store.path}')
        return 0
    except (ValueError, OSError, sqlite3.Error):
        print('Operación no completada: revise duración, sesión activa, base y destino nuevo; sin detalles sensibles.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
