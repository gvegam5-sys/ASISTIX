"""Synthetic-only attendance integration for the isolated 12.6.4 instance."""
from datetime import datetime, timedelta, timezone
import sqlite3
from contextlib import closing
from pathlib import Path
from secrets import token_bytes
from struct import pack, unpack
from threading import BoundedSemaphore, Lock
from typing import Literal
from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .attendance_errors import AttendanceError
from .biometric_schema import challenges, consent_epoch, policy, reviews, templates
from .db import biometric_key, get_db, private_pilot, settings
from .models import Attendance, Audit, ClassSession, Enrollment, QRToken, User, now
from .security import attendance_bearer, attendance_student, decode, roles


NOTICE = 'sintetico-12.6.4-v1'
PHYSICAL_NOTICE = 'voluntario-12.6.5.4-v1'
slots = BoundedSemaphore(8)  # Four running and at most four waiting.
running = BoundedSemaphore(4)
load_lock = Lock()
engine = None


class Consent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    explicit: StrictBool
    notice: Literal['sintetico-12.6.4-v1']


class Probe(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fixture: Literal['a', 'b']


class Review(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: int
    reason: Literal['technical', 'accessibility', 'no_consent', 'revoked', 'mismatch']


def require_lab():
    if not settings.biometric_lab or not settings.demo_mode:
        raise HTTPException(404, 'Modo biométrico experimental desactivado.')


def physical_capture(request, student_id):
    require_lab()
    capture = getattr(request.app.state, 'isolated_physical_capture', None)
    origin = getattr(request.app.state, 'physical_origin', None)
    if (not capture or request.url.scheme != 'https' or not origin or request.headers.get('origin') != origin
            or student_id != request.app.state.physical_student_id):
        raise HTTPException(404, 'Captura física experimental desactivada.')
    if request.headers.get('content-type') != 'image/jpeg' or request.url.query:
        raise HTTPException(415, 'Usa una captura JPEG del laboratorio.')
    return capture


def consent_revision(db, student_id):
    return db.scalar(select(consent_epoch.c.revision).where(consent_epoch.c.student_id==student_id)) or 0


async def jpeg_body(request):
    limit = 384 * 1024
    buffer = bytearray()
    async for chunk in request.stream():
        if len(buffer) + len(chunk) > limit:
            raise HTTPException(413, 'La captura supera el tamaño permitido.')
        buffer.extend(chunk)
    if len(buffer) < 4 or buffer[:2] != b'\xff\xd8' or buffer[-2:] != b'\xff\xd9':
        raise HTTPException(422, 'La captura JPEG no es válida.')
    return bytes(buffer)


def write_lock(db):
    # This dedicated runtime accepts SQLite only. Start a real write transaction
    # before re-reading any state; SELECT FOR UPDATE has no effect on SQLite.
    db.rollback()
    db.execute(text('BEGIN IMMEDIATE'))


def required(db, session_id):
    return db.scalar(select(policy.c.session_id).where(policy.c.session_id == session_id)) is not None


def current_template(db, student_id):
    row = db.execute(select(templates).where(templates.c.student_id == student_id)).mappings().first()
    if row:
        with closing(open_revocations()) as ledger:
            if not ledger.execute('SELECT 1 FROM active WHERE version = ?', (row['version'],)).fetchone():
                return None
    return row


def open_revocations():
    # Restore academic SQLite independently of this revocation ledger.
    path = (biometric_key.parent.parent / 'state/revocations.db' if private_pilot else
            Path(settings.biometric_key_file).resolve().with_name('revocations.db'))
    return sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)


def initialize_revocations():
    path = Path(settings.biometric_key_file).resolve().with_name('revocations.db')
    if path.exists():
        raise RuntimeError('Revocation ledger already exists')
    with closing(sqlite3.connect(path)) as ledger, ledger:
        ledger.execute('CREATE TABLE active (version TEXT PRIMARY KEY NOT NULL)')
        from .db import SessionLocal
        with SessionLocal() as db:
            ledger.executemany('INSERT INTO active VALUES (?)', [(v,) for v in db.scalars(select(templates.c.version))])



def assigned_fixture(student_id):
    return 'a' if student_id % 2 else 'b'


def crypt():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key_file = Path(settings.biometric_key_file).resolve()
    if key_file != biometric_key or len(key := key_file.read_bytes()) != 32:
        raise RuntimeError('Invalid laboratory encryption configuration')
    return AESGCM(key)


def associated(student_id, version, notice=NOTICE):
    identity=f'sface-2021dec|{student_id}|{version}'
    return (f'{identity}|{notice}' if notice==PHYSICAL_NOTICE else identity).encode()


def embed(fixture):
    global engine
    if not slots.acquire(blocking=False):
        raise AttendanceError('BIOMETRIC_BUSY', 503)
    try:
        if not running.acquire(timeout=1.0):
            raise AttendanceError('BIOMETRIC_BUSY', 503)
        try:
            with load_lock:
                if engine is None:
                    from .isolated_fixture_inference import IsolatedFixtureEngine
                    engine = IsolatedFixtureEngine()
            return engine.embed(fixture)
        except Exception:
            raise AttendanceError('BIOMETRIC_UNAVAILABLE', 503) from None
        finally:
            running.release()
    finally:
        slots.release()


def challenge_row(db, identifier, student_id):
    row = db.execute(select(challenges).where(
        challenges.c.id == identifier, challenges.c.student_id == student_id,
    )).mappings().first()
    if not row or row['closed_at'] is not None:
        raise AttendanceError('CHALLENGE_INVALID', 409)
    return row


def check_challenge(db, row, check_enrollment, *, check_duplicate):
    stamp = now()
    qr = db.get(QRToken, row['qr_id'])
    if qr is None or qr.session_id != row['session_id']:
        raise AttendanceError('QR_INVALID', 400)
    if qr.expires_at <= stamp:
        raise AttendanceError('QR_EXPIRED', 400)
    if row['expires_at'] <= stamp:
        raise AttendanceError('CHALLENGE_EXPIRED', 409)
    session = db.get(ClassSession, row['session_id'])
    if session is None or session.closed_at:
        raise AttendanceError('CLASS_CLOSED', 409)
    user = db.get(User, row['student_id'])
    if user is None or not user.active or user.role != 'student':
        raise AttendanceError('AUTH_INVALID', 401)
    if not required(db, session.id):
        raise AttendanceError('CHALLENGE_INVALID', 409)
    check_enrollment(db, session, user.id, check_duplicate=check_duplicate)
    template = current_template(db, user.id)
    if template is None or template['version'] != row['template_version']:
        raise AttendanceError('BIOMETRIC_TEMPLATE_CHANGED', 409)
    return template


def install(router, validate_qr, check_enrollment, save_attendance, course_access, scan_body):
    staff = roles('teacher', 'admin')

    @router.get('/biometric/status')
    def status(request: Request, u: User = Depends(attendance_student), db: Session = Depends(get_db)):
        require_lab()
        physical = bool(getattr(request.app.state, 'isolated_physical_capture', None))
        if physical and u.id != request.app.state.physical_student_id:
            raise HTTPException(403, 'Cuenta no autorizada para el piloto físico.')
        notice = PHYSICAL_NOTICE if physical else NOTICE
        template = current_template(db, u.id)
        return {'enrolled': bool(template and template['notice']==notice), 'physical_capture': physical,
                'fixture': None if private_pilot or physical else assigned_fixture(u.id), 'notice': notice}

    def save_template(db, student_id, vector, notice, revision=None):
        write_lock(db)
        if revision is not None and consent_revision(db, student_id)!=revision:
            raise AttendanceError('BIOMETRIC_TEMPLATE_CHANGED', 409)
        user = db.get(User, student_id)
        if user is None or not user.active or user.role != 'student':
            raise AttendanceError('AUTH_INVALID', 401)
        if current_template(db, student_id):
            raise HTTPException(409, 'Retira el registro vigente antes de volver a enrolar.')
        db.execute(delete(templates).where(templates.c.student_id == student_id))
        version, nonce = uuid4().hex, token_bytes(12)
        ciphertext = crypt().encrypt(nonce, pack('!128d', *vector), associated(student_id, version, notice))
        db.execute(insert(templates).values(student_id=student_id, version=version, notice=notice,
                                           consented_at=now(), nonce=nonce, ciphertext=ciphertext))
        with closing(open_revocations()) as ledger, ledger:
            ledger.execute('INSERT INTO active VALUES (?)', (version,))
        db.commit()
        return {'enrolled': True}

    @router.post('/biometric/enrollment', status_code=201)
    def enroll(body: Consent, request: Request, u: User = Depends(attendance_student), db: Session = Depends(get_db)):
        require_lab()
        if private_pilot or getattr(request.app.state, 'isolated_physical_capture', None):
            raise HTTPException(404, 'Catálogo sintético desactivado en el piloto físico.')
        if not body.explicit:
            raise HTTPException(422, 'Se requiere consentimiento explícito.')
        student_id = u.id
        db.rollback()
        vector = embed(assigned_fixture(student_id))
        return save_template(db, student_id, vector, NOTICE)

    @router.delete('/biometric/enrollment')
    def revoke(u: User = Depends(attendance_student), db: Session = Depends(get_db)):
        require_lab()
        student_id = u.id
        write_lock(db)
        revision = consent_revision(db, student_id)
        if revision:
            db.execute(update(consent_epoch).where(consent_epoch.c.student_id==student_id).values(revision=revision+1))
        else:
            db.execute(insert(consent_epoch).values(student_id=student_id, revision=1))
        row = db.execute(select(templates.c.version).where(templates.c.student_id == student_id)).scalar_one_or_none()
        if row:
            with closing(open_revocations()) as ledger, ledger:
                ledger.execute('DELETE FROM active WHERE version = ?', (row,))
        db.execute(delete(templates).where(templates.c.student_id == student_id))
        db.execute(update(challenges).where(challenges.c.student_id == student_id,
                          challenges.c.closed_at.is_(None)).values(closed_at=now()))
        db.commit()
        return {'enrolled': False}

    @router.get('/sessions/{session_id}/biometric')
    def policy_status(session_id: int, u: User = Depends(staff), db: Session = Depends(get_db)):
        require_lab()
        session = db.get(ClassSession, session_id)
        if session is None:
            raise HTTPException(404, 'No se encontró la sesión.')
        course_access(db, u, session.course_id)
        return {'required': required(db, session_id)}

    @router.put('/sessions/{session_id}/biometric')
    def activate(session_id: int, u: User = Depends(staff), db: Session = Depends(get_db)):
        require_lab()
        write_lock(db)
        session = db.get(ClassSession, session_id)
        if session is None or session.closed_at:
            raise HTTPException(404, 'Sesión abierta no disponible.')
        course_access(db, u, session.course_id)
        if not required(db, session.id):
            db.execute(insert(policy).values(session_id=session.id))
        db.commit()
        return {'required': True}

    @router.delete('/sessions/{session_id}/biometric')
    def deactivate(session_id: int, u: User = Depends(staff), db: Session = Depends(get_db)):
        require_lab()
        write_lock(db)
        session = db.get(ClassSession, session_id)
        if session is None or session.closed_at:
            raise HTTPException(404, 'Sesión abierta no disponible.')
        course_access(db, u, session.course_id)
        db.execute(delete(policy).where(policy.c.session_id==session_id))
        db.execute(update(challenges).where(challenges.c.session_id==session_id,
                                           challenges.c.closed_at.is_(None)).values(closed_at=now()))
        db.commit()
        return {'required': False}

    # Resolve the existing QR body type without making this module import main.
    @router.post('/biometric/challenges', status_code=201)
    def issue(data: scan_body, request: Request, u: User = Depends(attendance_student), db: Session = Depends(get_db)):
        require_lab()
        student_id = u.id
        write_lock(db)
        payload, qr, session = validate_qr(data.token, student_id, db)
        if not required(db, session.id):
            raise HTTPException(409, 'La sesión usa el flujo QR convencional.')
        template = current_template(db, student_id)
        physical = bool(getattr(request.app.state, 'isolated_physical_capture', None))
        if template is None or template['notice']!=(PHYSICAL_NOTICE if physical else NOTICE):
            # This authorized response provides a route to help without issuing a challenge.
            return {'enrolled': False, 'session_id': session.id,
                    'message': 'Completa el registro facial o solicita revisión docente.'}
        expires = min(qr.expires_at, datetime.fromtimestamp(payload['exp'], timezone.utc).replace(tzinfo=None),
                      now() + timedelta(seconds=20))
        if expires <= now():
            raise AttendanceError('QR_EXPIRED', 400)
        identifier = uuid4().hex
        db.execute(insert(challenges).values(id=identifier, student_id=student_id, session_id=session.id,
                   qr_id=qr.id, template_version=template['version'], expires_at=expires))
        db.commit()
        return {'challenge': identifier, 'session_id': session.id, 'expires_at': expires.isoformat() + 'Z'}

    @router.delete('/biometric/challenges/{identifier}')
    def cancel(identifier: str, u: User = Depends(attendance_student), db: Session = Depends(get_db)):
        require_lab()
        student_id = u.id
        write_lock(db)
        row = challenge_row(db, identifier, student_id)
        db.execute(update(challenges).where(challenges.c.id == row['id']).values(closed_at=now()))
        db.commit()
        return {'cancelled': True}

    def check_probe(db, identifier, student_id, notice):
        row = challenge_row(db, identifier, student_id)
        template = check_challenge(db, row, check_enrollment, check_duplicate=True)
        if template['notice'] != notice:
            raise AttendanceError('BIOMETRIC_TEMPLATE_CHANGED', 409)
        db.rollback()
        return template

    def commit_probe(db, identifier, student_id, template, probe, credentials):
        write_lock(db)
        if int(decode(credentials.credentials, 'access', attendance=True)['sub']) != student_id:
            raise AttendanceError('AUTH_INVALID', 401)
        row = challenge_row(db, identifier, student_id)
        current = check_challenge(db, row, check_enrollment, check_duplicate=True)
        if dict(current) != dict(template):
            raise AttendanceError('BIOMETRIC_TEMPLATE_CHANGED', 409)
        try:
            reference = unpack('!128d', crypt().decrypt(template['nonce'], template['ciphertext'],
                                                       associated(student_id, template['version'], template['notice'])))
        except Exception:
            raise AttendanceError('BIOMETRIC_UNAVAILABLE', 503) from None
        from .pilot_comparison import DEFAULT_THRESHOLD, FORMAT, matches
        try:
            matched = matches(FORMAT.pack(*reference), FORMAT.pack(*probe), DEFAULT_THRESHOLD)
        except (OverflowError, ValueError):
            raise AttendanceError('BIOMETRIC_UNAVAILABLE', 503) from None
        if not matched:
            raise AttendanceError('BIOMETRIC_MISMATCH', 409)
        consumed = db.execute(update(challenges).where(challenges.c.id == identifier,
                            challenges.c.closed_at.is_(None)).values(closed_at=now()))
        if consumed.rowcount != 1:
            raise AttendanceError('CHALLENGE_INVALID', 409)
        return save_attendance(db, student_id, row['session_id'], row['qr_id'])

    @router.post('/biometric/challenges/{identifier}/confirm', status_code=201)
    def confirm(identifier: str, body: Probe, request: Request, u: User = Depends(attendance_student),
                db: Session = Depends(get_db), credentials: HTTPAuthorizationCredentials = Depends(attendance_bearer)):
        require_lab()
        if private_pilot or getattr(request.app.state, 'isolated_physical_capture', None):
            raise HTTPException(404, 'Catálogo sintético desactivado en el piloto físico.')
        student_id = u.id
        template = check_probe(db, identifier, student_id, NOTICE)
        return commit_probe(db, identifier, student_id, template, embed(body.fixture), credentials)

    @router.post('/biometric/physical/enrollment', status_code=201)
    async def enroll_physical(request: Request, u: User = Depends(attendance_student), db: Session = Depends(get_db),
                              credentials: HTTPAuthorizationCredentials = Depends(attendance_bearer)):
        student_id = u.id
        capture = physical_capture(request, student_id)
        if request.headers.get('x-explicit-consent') != 'yes' or request.headers.get('x-consent-notice') != PHYSICAL_NOTICE:
            raise HTTPException(422, 'Debes aceptar el aviso de consentimiento vigente.')
        if current_template(db, student_id):
            raise HTTPException(409, 'Retira el registro vigente antes de volver a enrolar.')
        revision = consent_revision(db, student_id)
        db.rollback()
        vector = await run_in_threadpool(capture, student_id, await jpeg_body(request))
        if int(decode(credentials.credentials, 'access', attendance=True)['sub']) != student_id:
            raise AttendanceError('AUTH_INVALID', 401)
        return save_template(db, student_id, vector, PHYSICAL_NOTICE, revision)

    @router.post('/biometric/physical/challenges/{identifier}/confirm', status_code=201)
    async def confirm_physical(identifier: str, request: Request, u: User = Depends(attendance_student),
                               db: Session = Depends(get_db), credentials: HTTPAuthorizationCredentials = Depends(attendance_bearer)):
        student_id = u.id
        capture = physical_capture(request, student_id)
        template = check_probe(db, identifier, student_id, PHYSICAL_NOTICE)
        vector = await run_in_threadpool(capture, student_id, await jpeg_body(request))
        return commit_probe(db, identifier, student_id, template, vector, credentials)

    @router.post('/biometric/reviews', status_code=202)
    def request_review(body: Review, u: User = Depends(attendance_student), db: Session = Depends(get_db)):
        require_lab()
        student_id = u.id
        write_lock(db)
        session = db.get(ClassSession, body.session_id)
        if not session or not required(db, session.id):
            raise HTTPException(404, 'Sesión biométrica no disponible.')
        check_enrollment(db, session, student_id)
        existing = db.execute(select(reviews.c.id).where(reviews.c.session_id == session.id,
                              reviews.c.student_id == student_id)).scalar_one_or_none()
        if existing:
            return {'id': existing, 'status': 'pending'}
        identifier = uuid4().hex
        db.execute(insert(reviews).values(id=identifier, student_id=student_id, session_id=session.id,
                                         reason=body.reason, created_at=now()))
        db.commit()
        return {'id': identifier, 'status': 'pending'}

    @router.get('/sessions/{session_id}/biometric/reviews')
    def review_queue(session_id: int, u: User = Depends(staff), db: Session = Depends(get_db)):
        require_lab()
        session = db.get(ClassSession, session_id)
        if not session:
            raise HTTPException(404, 'Sesión no disponible.')
        course_access(db, u, session.course_id)
        return [dict(row) for row in db.execute(
            select(reviews.c.id, User.name.label('student_name'), reviews.c.reason, reviews.c.approved_at)
            .join(User, User.id == reviews.c.student_id)
            .where(reviews.c.session_id == session_id)
            .order_by(reviews.c.approved_at, reviews.c.created_at)
        ).mappings()]

    @router.post('/biometric/reviews/{identifier}/approve')
    def approve(identifier: str, u: User = Depends(staff), db: Session = Depends(get_db)):
        require_lab()
        write_lock(db)
        entry = db.execute(select(reviews).where(reviews.c.id == identifier)).mappings().first()
        if entry is None:
            raise HTTPException(404, 'Solicitud no disponible.')
        session = db.get(ClassSession, entry['session_id'])
        if session is None:
            raise HTTPException(404, 'Sesión no disponible.')
        course_access(db, u, session.course_id)
        if entry['approved_at'] is not None:
            raise HTTPException(409, 'La solicitud ya se resolvió.')
        student = db.get(User, entry['student_id'])
        if not student or not student.active or student.role != 'student':
            raise AttendanceError('AUTH_INVALID', 401)
        check_enrollment(db, session, student.id)
        db.execute(update(reviews).where(reviews.c.id == identifier).values(approved_at=now(), approved_by=u.id))
        db.add(Audit(actor_id=u.id, action=f'biometric_review_approved:{session.id}:{student.id}'))
        return save_attendance(db, student.id, session.id, None, refresh_course_id=session.course_id if session.closed_at else None)
