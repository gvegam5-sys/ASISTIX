"""Loopback-only presentation. PAD outcomes are simulated for fixed fixtures."""
from ipaddress import ip_address

from fastapi import Request
from fastapi.responses import JSONResponse

from .biometric_attendance import assigned_fixture, embed
from .db import private_pilot, settings
from .liveness import LivenessRejected, VerifiedProbe
from .main import app


if private_pilot or not (settings.demo_mode and settings.biometric_lab):
    raise RuntimeError('The presentation requires a dedicated synthetic laboratory')


def synthetic_probe(plan, fixture):
    if fixture != assigned_fixture(plan.student_id):
        raise LivenessRejected()
    return VerifiedProbe(plan, tuple(embed(fixture)))


app.state.synthetic_liveness_adapter = synthetic_probe


@app.middleware('http')
async def restrict_demo(request: Request, call_next):
    try:
        local = request.client is not None and ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    if not local:
        return JSONResponse({'detail': 'Demostración disponible solo en este equipo.'}, status_code=403)
    response = await call_next(request)
    response.headers['Permissions-Policy'] = 'camera=(), microphone=()'
    return response
