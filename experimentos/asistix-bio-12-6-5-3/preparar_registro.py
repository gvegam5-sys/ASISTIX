"""Initialize the enrollment schema on the dedicated pilot database only."""
from contextlib import closing
from pathlib import Path
import sqlite3

from registro import ROOT, Store


def main():
    path = ROOT / 'runtime/asistix-bio-piloto.db'
    if not path.is_file() or path.resolve() != path or path.stat().st_nlink != 1:
        raise RuntimeError('Base piloto ausente, redirigida o compartida.')
    expected = {'lab_metadata', 'pilot_accounts', 'pilot_templates'}
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        tables = {name for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'lab_metadata' not in tables or not tables <= expected:
            raise RuntimeError('Esquema SQLite ajeno al piloto.')
        values = dict(db.execute('SELECT key,value FROM lab_metadata'))
        if values.get('phase') != '12.6.5.1' or values.get('real_capture') != 'disabled':
            raise RuntimeError('Falta la marca de aislamiento o el bloqueo de captura.')
    Store(path).prepare()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        integrity = db.execute('PRAGMA integrity_check').fetchone()
        registered = db.execute('SELECT count(*) FROM pilot_templates').fetchone()
        participants = db.execute('SELECT count(*) FROM pilot_accounts').fetchone()
    if integrity != ('ok',) or registered != (0,) or participants != (0,):
        raise RuntimeError('La base de preparaci\u00f3n no est\u00e1 vac\u00eda o \u00edntegra.')
    print('Esquema piloto preparado. Sin participantes, plantillas ni asistencias.')


if __name__ == '__main__':
    main()
