from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from test_flow import login
from app.analytics import calculate_risk, risk_policy
from app.db import SessionLocal, Settings
from app.models import Attendance, ClassSession, Course, Enrollment, User


@pytest.mark.parametrize(('flags', 'level', 'streak'), [
    ([], 'sin_datos', 0), ([0, 0], 'sin_datos', 2), ([1] * 4 + [0], 'bajo', 1),
    ([1] * 5 + [0, 1, 0, 0], 'alto', 2),
    ([1] * 8 + [0, 0], 'medio', 2), ([1] * 9 + [0, 0, 0], 'alto', 3),
    ([1] * 7 + [0, 0, 1, 0], 'medio', 1), ([0, 0, 0] + [1] * 12, 'bajo', 0),
    ([1] * 6 + [0, 1, 0, 0], 'medio', 2),
    ([0] * 3 + [1] * 7, 'medio', 0),
    ([0] * 2 + [1] * 8, 'bajo', 0),
    ([1] * 7 + [0], 'bajo', 1),
    ([1] * 9 + [0, 0], 'medio', 2),
    ([1] * 13 + [0, 0, 0], 'alto', 3),
])
def test_risk_rules(flags, level, streak):
    stats = calculate_risk([(None, flag) for flag in flags], risk_policy())
    assert (stats['level'], stats['consecutive']) == (level, streak)
    assert stats['absent'] == flags.count(0)
    assert bool(stats['reasons']) == (level in ('medio', 'alto'))


def test_configuration(monkeypatch):
    monkeypatch.setenv('ABSENTEEISM_MIN_SESSIONS', '5')
    monkeypatch.setenv('ABSENTEEISM_HIGH_BELOW', '60')
    monkeypatch.setenv('ABSENTEEISM_MEDIUM_BELOW', '75')
    monkeypatch.setenv('ABSENTEEISM_HIGH_STREAK', '4')
    monkeypatch.setenv('ABSENTEEISM_MEDIUM_STREAK', '3')
    configured = Settings()
    policy = {key: getattr(configured, f'absenteeism_{key}') for key in risk_policy()}
    assert calculate_risk([(None, 0)] * 4, policy)['level'] == 'sin_datos'
    assert calculate_risk([(None, x) for x in [1, 1, 1, 0, 0, 1]], policy)['level'] == 'medio'
    with pytest.raises(ValueError, match='umbrales'):
        Settings(absenteeism_high_below=85, absenteeism_medium_below=80)
    with pytest.raises(ValueError, match='umbrales'):
        Settings(absenteeism_high_streak=3, absenteeism_medium_streak=3)
    with pytest.raises(ValueError):
        Settings(absenteeism_min_sessions=0)
    with pytest.raises(ValueError):
        Settings(absenteeism_medium_below=101)


def test_dashboard_scopes_and_valid_sessions(client, monkeypatch):
    from app import main

    cutoff = datetime(2035, 1, 15, 15)
    monkeypatch.setattr(main, 'now', lambda: cutoff)
    admin = login(client, 'admin')
    teacher = login(client, 'docente')
    student = login(client, 'estudiante')
    other = client.post('/users', headers=admin, json={
        'name': 'Docente externo', 'email': 'externo@example.com', 'password': 'Ficticia2026!', 'role': 'teacher',
    }).json()
    with SessionLocal() as db:
        student_id = db.scalar(select(User.id).where(User.email == 'estudiante@asistix.demo'))
        classmate_id = db.scalar(select(User.id).where(User.email == 'estudiante2@asistix.demo'))
        db.query(Attendance).delete()
        db.query(ClassSession).delete()
        course = Course(name='Materia reservada', code='RES-12', teacher_id=other['id'])
        db.add(course)
        db.flush()
        db.add(Enrollment(course_id=course.id, student_id=classmate_id, created_at=cutoff - timedelta(days=20)))
        for enrollment in db.scalars(select(Enrollment).where(Enrollment.course_id == 1)):
            enrollment.created_at = cutoff - timedelta(days=20)
        for start, end in [(-22, -21), (-10, -9), (-2, -1), (-1, None), (1, 2), (-1, 1), (-3, -4)]:
            session = ClassSession(course_id=1, started_at=cutoff + timedelta(days=start),
                                   closed_at=cutoff + timedelta(days=end) if end is not None else None)
            db.add(session)
            db.flush()
            if start == -2:
                db.add(Attendance(student_id=student_id, session_id=session.id,
                                  registered_at=session.started_at))
        db.add(ClassSession(course_id=course.id, started_at=cutoff - timedelta(days=2),
                            closed_at=cutoff - timedelta(days=1)))
        db.commit()

    assert client.get('/dashboard').status_code in (401, 403)
    personal = client.get('/dashboard', headers=student).json()
    staff = client.get('/dashboard', headers=teacher).json()
    institution = client.get('/dashboard', headers=admin).json()
    assert {row['student'] for row in personal['students_stats']} == {'Isaac Mendoza'}
    assert not personal['absenteeism']['top_students']
    assert 'Materia reservada' not in str(staff)
    assert institution['absenteeism']['top_courses'][0]['name'] == 'Materia reservada'
    assert institution['absenteeism']['top_students'][0]['rate'] == 100
    row = next(row for row in personal['students_stats'] if row['course'] == 'Ingeniería de Software')
    assert (row['total'], row['absent'], row['level'], row['consecutive']) == (2, 1, 'sin_datos', 0)
    trend = personal['absenteeism']['trend']
    assert trend['previous']['expected'] == trend['current']['expected'] == 1
    assert trend['change'] == 100
    assert not personal['alerts']
    assert any(row['total'] == 0 and row['rate'] is None for row in personal['students_stats'])
