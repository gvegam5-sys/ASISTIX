"""12.6.5.4 demonstration adapter. Only a fixed synthetic catalog reaches IPC."""

from hashlib import sha256
from importlib import import_module
from pathlib import Path
import subprocess
import sys
from threading import Lock

import cv2
import numpy as np


PILOT = Path(__file__).resolve().parents[3] / 'asistix-bio-12-6-5-3'
FIXTURES = {
    'a': ('portrait-a.png', '6aa9dd462536a465e5e08cd40e772cfc0d2c7db014055b4f0e2993371604bb82'),
    'b': ('portrait-b.png', 'cfbc2e01cd75ae434cc2f319dd7a73c2f2c3f1fc6c0caac4b8a4c144b59fe05c'),
}
launch_lock = Lock()

with launch_lock:
    sys.path.insert(0, str(PILOT))
    try:
        sandbox = import_module('appcontainer_piloto')
        comparison = import_module('comparacion_facial')
    finally:
        sys.path.pop(0)

if any(Path(module.__file__).resolve().parent != PILOT for module in (sandbox, comparison)):
    raise RuntimeError('Unexpected facial runtime')


class IsolatedFixtureEngine:
    def embed(self, fixture):
        name, checksum = FIXTURES[fixture]
        source = (PILOT / 'engine' / name).read_bytes()
        if sha256(source).hexdigest() != checksum:
            raise ValueError('Unexpected synthetic fixture')
        image = cv2.imdecode(np.frombuffer(source, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('Invalid synthetic fixture')
        ok, jpeg = cv2.imencode('.jpg', cv2.resize(image, (640, 640)))
        if not ok:
            raise ValueError('Could not encode synthetic fixture')
        return self.infer_frame(jpeg.tobytes())

    def infer_frame(self, frame):
        with launch_lock, sandbox.appcontainer_creation():
            worker = subprocess.Popen(
                [str(sandbox.EXECUTABLE), '-B', '-I', str(sandbox.STAGE / 'worker_sintetico_ipc.py')],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        with worker:
            try:
                vector, _ = worker.communicate(len(frame).to_bytes(4, 'big') + frame, timeout=9)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.communicate()
                raise
            if worker.returncode:
                raise RuntimeError('Isolated worker failed')
        return comparison.vector(vector)
