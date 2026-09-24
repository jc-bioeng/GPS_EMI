"""Exportación de lectura exclusivamente; no carga .env ni consulta al proveedor."""
import argparse
import csv
from datetime import datetime
import os
from pathlib import Path
import sqlite3

from .collector import DEFAULT_DB, EXPORT_COLUMNS, utc_text


def timestamp(value):
    try:
        return utc_text(datetime.fromisoformat(value))
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError('Use fecha ISO 8601 con offset o Z.') from None


def export_csv(db, output, start=None, end=None):
    db, output = Path(db).resolve(), Path(output).resolve()
    if db == output:
        raise ValueError('El destino debe ser distinto de la base.')
    if start and end and start >= end:
        raise ValueError('El inicio debe ser anterior al fin.')
    connection = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
    try:
        where, params = [], []
        for operator, value in (('>=', start), ('<', end)):
            if value:
                where.append('acquired_at ' + operator + ' ?')
                params.append(value)
        query = 'SELECT ' + ','.join(EXPORT_COLUMNS) + ' FROM gps_observations'
        if where:
            query += ' WHERE ' + ' AND '.join(where)
        cursor = connection.execute(query + ' ORDER BY acquired_at, id', params)
        # No sobrescribir exportaciones existentes ni otros archivos locales.
        with output.open('x', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(EXPORT_COLUMNS)
            count = 0
            for row in cursor:
                writer.writerow(row)
                count += 1
        return count
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Exportar observaciones GPS crudas a CSV UTF-8.')
    parser.add_argument('--db', default=os.environ.get('GPS_EMI_DATA_DB', DEFAULT_DB))
    parser.add_argument('--output', required=True)
    parser.add_argument('--from', dest='start', type=timestamp)
    parser.add_argument('--to', dest='end', type=timestamp)
    args = parser.parse_args(argv)
    try:
        count = export_csv(args.db, args.output, args.start, args.end)
    except (sqlite3.Error, OSError, ValueError):
        print('Exportación fallida: revise base, rango y destino nuevo. No se modificó la base.')
        return 1
    print(f'Observaciones exportadas: {count}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
