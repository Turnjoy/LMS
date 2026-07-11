import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _row_counts(connection, tables):
    counts = {}
    for table in tables:
        counts[table.name] = connection.execute(
            text(f'SELECT COUNT(*) FROM "{table.name}"')
        ).scalar_one()
    return counts


def _clear_sqlite(connection, tables):
    connection.execute(text('PRAGMA foreign_keys=OFF'))
    for table in reversed(tables):
        connection.execute(text(f'DELETE FROM "{table.name}"'))
    has_sequence_table = connection.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
    )).first()
    if has_sequence_table:
        connection.execute(text('DELETE FROM sqlite_sequence'))
    connection.execute(text('PRAGMA foreign_keys=ON'))


def _clear_postgres(connection, tables):
    table_names = ', '.join(f'"{table.name}"' for table in tables)
    if table_names:
        connection.execute(text(f'TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE'))


def main():
    parser = argparse.ArgumentParser(description='Delete application data while keeping the database schema.')
    parser.add_argument('--database-url', help='Optional database URL. If omitted, the configured development database is used.')
    args = parser.parse_args()

    if args.database_url:
        os.environ['DATABASE_URL'] = args.database_url

    from app import create_app, db

    app = create_app('development')
    with app.app_context():
        tables = [table for table in db.metadata.sorted_tables if table.name != 'alembic_version']
        engine = db.engine
        with engine.begin() as connection:
            before = _row_counts(connection, tables)
            if engine.dialect.name == 'sqlite':
                _clear_sqlite(connection, tables)
            elif engine.dialect.name in ('postgresql', 'postgres'):
                _clear_postgres(connection, tables)
            else:
                raise RuntimeError(f'Unsupported database dialect: {engine.dialect.name}')
            after = _row_counts(connection, tables)

        print(f'Cleared data from {len(tables)} tables on {engine.dialect.name}.')
        print(f'Rows before: {sum(before.values())}')
        print(f'Rows after: {sum(after.values())}')


if __name__ == '__main__':
    main()
