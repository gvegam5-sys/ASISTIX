"""ASGI entry for the isolated TLS gateway. Ordinary Uvicorn never arms it."""
from collections import deque
from pathlib import Path
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .attendance_errors import AttendanceError
from .db import settings
from .main import app as academic
from .pilot_comparison import vector


def build_gateway(*, origin, worker_capture, web_root, student_id, armed=False):
    # This is an operating-system token check, not a client claim.
    from comprobar_aislamiento import is_appcontainer
    host = urlsplit(origin)
    if (not is_appcontainer() or not settings.demo_mode or not settings.biometric_lab
            or host.scheme != 'https' or origin != f'https://{host.netloc}'
            or not host.hostname or host.username or not Path(web_root, 'index.html').is_file()):
        raise RuntimeError('The academic gateway requires the restricted pilot')
    if type(student_id) is not int or student_id < 1:
        raise RuntimeError('Invalid volunteer account')

    lock = Lock()
    attempts = deque()
    running = False

    def capture(account, jpeg):
        nonlocal running
        with lock:
            stamp = monotonic()
            while attempts and attempts[0] <= stamp-60:
                attempts.popleft()
            if account != student_id or running or len(attempts) >= 5:
                raise AttendanceError('BIOMETRIC_BUSY', 429)
            attempts.append(stamp)
            running = True
        try:
            return vector(worker_capture(jpeg))
        except AttendanceError:
            raise
        except Exception as error:
            if type(error).__name__ == 'CaptureError':
                raise AttendanceError('BIOMETRIC_CAPTURE_QUALITY', 422) from None
            raise AttendanceError('BIOMETRIC_UNAVAILABLE', 503) from None
        finally:
            with lock:
                running = False

    academic.state.physical_student_id = student_id
    academic.state.physical_origin = origin
    academic.state.isolated_physical_capture = capture if armed else None
    gateway = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @gateway.middleware('http')
    async def local_only(request: Request, call_next):
        peer = request.client.host if request.client else ''
        if (peer != '127.0.0.1' or request.url.scheme != 'https' or request.headers.get('host') != host.netloc
                or (request.method in {'POST','PUT','DELETE','PATCH'} and request.headers.get('origin') != origin)):
            response = JSONResponse({'detail':'Acceso fuera del laboratorio autorizado.'}, status_code=403)
        elif not armed and request.url.path.startswith('/api/biometric/physical/'):
            response = JSONResponse({'detail':'Captura física desactivada.'}, status_code=404)
        else:
            response = await call_next(request)
        response.headers.update({
            'Cache-Control': 'no-store',
            'Referrer-Policy': 'no-referrer',
            'X-Content-Type-Options': 'nosniff',
            'Permissions-Policy': f'camera={"(self)" if armed else "()"}, microphone=()',
            'Content-Security-Policy': ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                        "connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
                                        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
        })
        return response

    gateway.mount('/api', academic)
    gateway.mount('/', StaticFiles(directory=web_root, html=True), name='asistix')
    return gateway
