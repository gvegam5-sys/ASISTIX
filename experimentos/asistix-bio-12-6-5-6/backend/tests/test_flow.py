import os
import tempfile
from datetime import timedelta

directory = tempfile.TemporaryDirectory()
os.environ['DATABASE_URL'] = 'sqlite:///' + directory.name.replace('\\', '/') + '/test.db'
os.environ['JWT_SECRET'] = 'test-secret-only-for-automated-tests-000000'
os.environ['DEMO_MODE'] = 'true'

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.main import app
from app.seed import seed
from app.db import SessionLocal, Base, engine
from app.models import User, Attendance, QRToken, ClassSession, Enrollment, now
from app.security import sign


@pytest.fixture()
def client():
    from app.main import attempts
    attempts.clear()
    Base.metadata.drop_all(engine)
    with TestClient(app) as client:
        seed()
        yield client
    engine.dispose()  # Libera el archivo SQLite antes de limpiar temporales en Windows.


def login(client, name):
    response = client.post('/auth/login', json={'email': f'{name}@asistix.demo', 'password': 'Asistix2026!'})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def start(client, teacher):
    response = client.post('/courses/1/sessions', headers=teacher)
    assert response.status_code == 201
    session = response.json()['id']
    token = client.get(f'/sessions/{session}/qr', headers=teacher).json()['token']
    return session, token


def test_end_to_end_and_duplicates(client):
    teacher, student = login(client, 'docente'), login(client, 'estudiante')
    sid, token = start(client, teacher)
    assert client.post('/attendance', headers=student, json={'token': token}).status_code == 201
    assert client.post('/attendance', headers=student, json={'token': token}).status_code == 409
    roster = client.get(f'/sessions/{sid}/roster', headers=teacher).json()
    assert next(r for r in roster if r['name'] == 'Isaac Mendoza')['status'] == 'Presente'
    assert client.get('/dashboard', headers=teacher).json()['today'] == 1
    assert client.post(f'/sessions/{sid}/close', headers=teacher).status_code == 200
    assert client.get(f'/sessions/{sid}/qr', headers=teacher).status_code == 409
    assert client.post('/attendance', headers=student, json={'token': token}).status_code == 409
    assert client.get('/reports/attendance.csv', headers=student).status_code == 200


def test_roles_and_privacy(client):
    student = login(client, 'estudiante')
    teacher = login(client, 'docente')
    assert client.get('/users', headers=student).status_code == 403
    assert client.post('/courses/1/sessions', headers=student).status_code == 403
    assert client.get('/users', headers=teacher).status_code == 403
    assert client.get('/dashboard').status_code in (401, 403)
    history = client.get('/attendance', headers=student).json()
    assert all(r['student'] == 'Isaac Mendoza' for r in history)
    assert all(r['student'] == 'Isaac Mendoza' for r in client.get('/dashboard', headers=student).json()['students_stats'])


def test_expired_tampered_and_non_enrolled(client):
    teacher, student = login(client, 'docente'), login(client, 'estudiante')
    sid, token = start(client, teacher)
    assert client.post('/attendance', headers=student, json={'token': token[:-8]+'INVALID!'}).status_code == 401
    expired = sign({'kind': 'qr', 'jti': 'expired', 'sid': sid}, -1)
    assert client.post('/attendance', headers=student, json={'token': expired}).status_code == 401
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == 'estudiante@asistix.demo'))
        e = db.scalar(select(Enrollment).where(Enrollment.student_id == u.id, Enrollment.course_id == 1))
        db.delete(e); db.commit()
    assert client.post('/attendance', headers=student, json={'token': token}).status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Attendance).where(Attendance.session_id == sid)) == 0


def test_admin_management_and_teacher_isolation(client):
    admin = login(client, 'admin')
    teacher = login(client, 'docente')
    user = client.post('/users', headers=admin, json={'name':'Nuevo Docente','email':'nuevo@example.com','password':'Password2026!','role':'teacher'})
    assert user.status_code == 201
    course = client.post('/courses', headers=admin, json={'name':'Otra materia','code':'OT-01','teacher_id':user.json()['id']})
    assert course.status_code == 201
    assert client.post(f"/courses/{course.json()['id']}/sessions", headers=teacher).status_code == 404
    assert client.patch(f"/users/{user.json()['id']}", headers=admin, json={'active':False}).status_code == 200
    assert client.post('/auth/login', json={'email':'nuevo@example.com','password':'Password2026!'}).status_code == 401
    assert client.get('/audit', headers=admin).status_code == 200


def test_no_future_absences_and_analytics(client):
    from app.analytics import student_stats, experimental_model
    teacher = login(client, 'docente')
    with SessionLocal() as db:
        e = db.scalar(select(Enrollment).where(Enrollment.course_id == 1))
        before = student_stats(db, e)['total']
    sid, token = start(client, teacher)
    assert client.post('/courses/1/sessions', headers=teacher).status_code == 409
    with SessionLocal() as db:
        assert student_stats(db, db.get(Enrollment, e.id))['total'] == before
    client.post(f'/sessions/{sid}/close', headers=teacher)
    with SessionLocal() as db:
        assert student_stats(db, db.get(Enrollment, e.id))['total'] == before+1
    assert experimental_model([])['status'] == 'insufficient_data'


def test_unknown_qr_and_wrong_kind(client):
    teacher, student = login(client, 'docente'), login(client, 'estudiante')
    sid, token = start(client, teacher)
    unknown = sign({'kind':'qr','jti':'not-stored','sid':sid})
    assert client.post('/attendance', headers=student, json={'token':unknown}).status_code == 400
    assert client.post('/attendance', headers=student, json={'token':student['Authorization'].split()[1]}).status_code == 401
    with SessionLocal() as db:
        t = db.scalar(select(QRToken).where(QRToken.session_id == sid))
        t.expires_at = now()-timedelta(seconds=1); db.commit()
    assert client.post('/attendance', headers=student, json={'token':token}).status_code == 400


def test_shared_class_token_and_late_enrollment(client):
    teacher = login(client, 'docente')
    student = login(client, 'estudiante')
    other = login(client, 'estudiante2')
    sid, token = start(client, teacher)
    assert client.post('/attendance', headers=student, json={'token':token}).status_code == 201
    assert client.post('/attendance', headers=other, json={'token':token}).status_code == 201
    late = login(client, 'estudiante3')
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == 'estudiante3@asistix.demo'))
        e = db.scalar(select(Enrollment).where(Enrollment.student_id == u.id, Enrollment.course_id == 1))
        e.created_at = now()+timedelta(seconds=1)
        db.commit()
    assert client.post('/attendance', headers=late, json={'token':token}).status_code == 403


def test_statistical_rules_and_model_gate(client):
    admin = login(client, 'admin')
    result = client.post('/analytics/model', headers=admin)
    assert result.status_code == 200
    assert result.json()['status'] == 'insufficient_data'
    from app.analytics import student_stats
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == 'estudiante5@asistix.demo'))
        e = db.scalar(select(Enrollment).where(Enrollment.student_id == u.id, Enrollment.course_id == 1))
        stats = student_stats(db, e)
        assert stats['rate'] == 50
        assert stats['level'] == 'alto'


def assert_error(response, status, code):
    from app.attendance_errors import MESSAGES
    assert response.status_code == status
    assert response.json() == {'code': code, 'detail': MESSAGES[code]}


def test_qr_error_codes_and_legacy_detail(client):
    teacher, student = login(client, 'docente'), login(client, 'estudiante')
    sid, token = start(client, teacher)
    response = client.post('/attendance', headers=student, json={'token': token})
    assert response.json()['code'] == 'ATTENDANCE_RECORDED'
    assert_error(client.post('/attendance', headers=student, json={'token': token}), 409, 'ATTENDANCE_DUPLICATE')
    client.post(f'/sessions/{sid}/close', headers=teacher)
    assert_error(client.post('/attendance', headers=student, json={'token': token}), 409, 'CLASS_CLOSED')


@pytest.mark.parametrize('case,status,code', [
    ('expired', 401, 'QR_EXPIRED'), ('tampered', 401, 'QR_INVALID'),
    ('unknown', 400, 'QR_INVALID'), ('database_expired', 400, 'QR_EXPIRED'),
    ('wrong_kind', 401, 'QR_INVALID'), ('invalid_claim', 400, 'QR_INVALID'), ('invalid_jti', 401, 'QR_INVALID'),
    ('not_enrolled', 403, 'ENROLLMENT_INVALID'), ('late_enrollment', 403, 'ENROLLMENT_INVALID'),
])
def test_specific_qr_rejections(client, case, status, code):
    teacher, student = login(client, 'docente'), login(client, 'estudiante')
    sid, token = start(client, teacher)
    if case == 'expired': token = sign({'kind': 'qr', 'sid': sid, 'jti': 'test'}, -1)
    if case == 'tampered': token = token[:-8] + 'INVALID!'
    if case == 'unknown': token = sign({'kind': 'qr', 'sid': sid, 'jti': 'unknown'})
    if case == 'wrong_kind': token = student['Authorization'].split()[1]
    if case == 'invalid_claim': token = sign({'kind': 'qr', 'sid': [], 'jti': 'test'})
    if case == 'invalid_jti': token = sign({'kind': 'qr', 'sid': sid, 'jti': {}})
    with SessionLocal() as db:
        if case == 'database_expired':
            db.scalar(select(QRToken).where(QRToken.session_id == sid)).expires_at = now()-timedelta(seconds=1)
        if case in ('not_enrolled', 'late_enrollment'):
            u = db.scalar(select(User).where(User.email == 'estudiante@asistix.demo'))
            e = db.scalar(select(Enrollment).where(Enrollment.student_id == u.id, Enrollment.course_id == 1))
            if case == 'not_enrolled': db.delete(e)
            else: e.created_at = now()+timedelta(seconds=1)
        db.commit()
    response = client.post('/attendance', headers=student, json={'token': token})
    assert_error(response, status, code)
    assert token not in response.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Attendance).where(Attendance.session_id == sid)) == 0


@pytest.mark.parametrize('case,status,code', [
    ('missing', 401, 'AUTH_REQUIRED'), ('expired', 401, 'AUTH_EXPIRED'),
    ('invalid', 401, 'AUTH_INVALID'), ('invalid_subject', 401, 'AUTH_INVALID'),
    ('inactive', 401, 'AUTH_INVALID'), ('role', 403, 'ROLE_FORBIDDEN'),
])
def test_attendance_auth_messages(client, case, status, code):
    student = login(client, 'estudiante')
    if case == 'missing': student = {}
    if case in ('expired', 'invalid_subject'):
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == 'estudiante@asistix.demo'))
        token = sign({'kind': 'access', 'sub': str(user.id) if case == 'expired' else 'invalid'}, -1 if case == 'expired' else 3600)
        student = {'Authorization': 'Bearer '+token}
    if case == 'invalid': student = {'Authorization': 'Bearer invalid'}
    if case == 'inactive':
        with SessionLocal() as db:
            db.scalar(select(User).where(User.email == 'estudiante@asistix.demo')).active = False
            db.commit()
    if case == 'role': student = login(client, 'docente')
    assert_error(client.post('/attendance', headers=student, json={'token': 'untrusted-payload-123456'}), status, code)


@pytest.mark.parametrize('body', [{}, {'token': 'short'}, {'token': ['SENSITIVE_PAYLOAD']}, {'token': 's'*2049}])
def test_validation_never_echoes_qr(client, body):
    student = login(client, 'estudiante')
    response = client.post('/attendance', headers=student, json=body)
    assert_error(response, 422, 'QR_INVALID')
    assert 'SENSITIVE_PAYLOAD' not in response.text


@pytest.mark.parametrize('failure', ['integrity', 'database', 'unexpected'])
def test_internal_failures_are_not_duplicates_or_leaked(client, monkeypatch, failure):
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import IntegrityError, OperationalError
    teacher, student = login(client, 'docente'), login(client, 'estudiante')
    sid, token = start(client, teacher)
    errors = {
        'integrity': IntegrityError('SECRET SQL', {'secret': token}, Exception('SECRET DATABASE')),
        'database': OperationalError('SECRET SQL', {'secret': token}, Exception('SECRET DATABASE')),
        'unexpected': RuntimeError('SECRET INTERNAL'),
    }
    def fail_commit(self): raise errors[failure]
    monkeypatch.setattr(Session, 'commit', fail_commit)
    response = client.post('/attendance', headers=student, json={'token': token})
    assert_error(response, 500 if failure == 'unexpected' else 503, 'ATTENDANCE_UNAVAILABLE')
    assert 'SECRET' not in response.text and token not in response.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Attendance).where(Attendance.session_id == sid)) == 0
