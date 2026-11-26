"""Prepare 12.6.5.1 and benchmark only known synthetic images."""
from contextlib import closing
import hashlib
from importlib.metadata import metadata, version
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[1]
ENGINE = LAB / 'engine'
RUNTIME = LAB / 'runtime'
FIXTURES = {
    'portrait-a.png': '6aa9dd462536a465e5e08cd40e772cfc0d2c7db014055b4f0e2993371604bb82',
    'portrait-b.png': 'cfbc2e01cd75ae434cc2f319dd7a73c2f2c3f1fc6c0caac4b8a4c144b59fe05c',
    'models/face_detection_yunet_2023mar.onnx': '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4',
    'models/face_recognition_sface_2021dec.onnx': '0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79',
}


def prepare():
    if Path(sys.prefix).resolve() != LAB / '.venv' or sys.version_info[:3] != (3, 13, 7):
        raise RuntimeError('Se requiere Python 3.13.7 del entorno exclusivo.')
    ip = json.loads((ROOT / '.certs/https.json').read_text(encoding='utf-8-sig'))['lan_ip']
    for port in (8014, 5188):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(('0.0.0.0', port))
    for name, expected in FIXTURES.items():
        if hashlib.sha256((ENGINE / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f'Huella incorrecta: {name}')
    database = RUNTIME / 'asistix-bio-piloto.db'
    if database.exists() and (database.is_symlink() or database.stat().st_nlink != 1):
        raise RuntimeError('Base de piloto redirigida.')
    with closing(sqlite3.connect(database)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS lab_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if not {name for name, in tables} <= {'lab_metadata', 'pilot_accounts', 'pilot_templates'}:
            raise RuntimeError('La base contiene tablas ajenas a la fase 12.6.5.1.')
        db.execute("INSERT OR IGNORE INTO lab_metadata VALUES ('phase', '12.6.5.1')")
        db.execute("INSERT OR IGNORE INTO lab_metadata VALUES ('real_capture', 'disabled')")
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    config = {'api_host': '127.0.0.1', 'api_port': 8014, 'https_host_candidate': ip,
              'https_port': 5188, 'sqlite_file': 'runtime/asistix-bio-piloto.db',
              'real_capture': False, 'network_services_started': False}
    (LAB / 'lab-config.json').write_text(json.dumps(config, indent=2)+'\n', encoding='utf-8')
    print('Puertos 8014 y 5188 disponibles; SQLite exclusiva preparada; captura desactivada.', flush=True)


def evaluate():
    result = subprocess.run([sys.executable, '-B', '-I', 'benchmark.py', 'portrait-a.png',
                             '--second', 'portrait-b.png', '--engine', 'both', '--count', '16'],
                            cwd=ENGINE, capture_output=True, check=True, text=True)
    raw = json.loads(result.stdout)
    summary = {
        'python': raw['python'], 'opencv': raw['opencv'], 'onnxruntime': raw['onnxruntime'],
        'dependencies': {name: {'version': version(name), 'license': metadata(name).get('License-Expression')}
                         for name in ('onnxruntime', 'opencv-python-headless', 'numpy', 'cryptography')},
        'engine_parity_passed': 'parity' in raw['result'],
        'network': raw['network'],
    }
    for name in ('ort', 'opencv'):
        engine = raw['result'][name]
        summary[name] = {key: engine[key] for key in ('load_ms', 'memory_before', 'memory_loaded', 'memory_peak', 'concurrency')}
        summary[name]['case_results'] = {case: metrics['result'] for case, metrics in engine['cases'].items()}
    (LAB / 'resultados-sinteticos.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    prepare()
    evaluate()
