import csv
import io
from datetime import datetime

import pytest
from sqlalchemy import select

from test_flow import client, login
from app.db import SessionLocal
from app.models import Attendance, ClassSession, Course, Enrollment, Teacher, User


HISTORY = '/attendance'
CSV = '/reports/attendance.csv'


@pytest.fixture
def courses_with_attendance(client):
    with SessionLocal() as db:
        teacher = db.scalar(select(User).where(User.email == 'docente@asistix.demo'))
        second = User(name='Segundo docente', email='docente2@asistix.demo',
                      role='teacher', password_hash=teacher.password_hash)
        db.add(second)
        db.flush()
        db.add(Teacher(user_id=second.id))
        db.flush()
        first_course = Course(code='FILTRO-1', name='Materia de filtros', teacher_id=teacher.id)
        second_course = Course(code='FILTRO-2', name='Materia ajena', teacher_id=second.id)
        db.add_all([first_course, second_course])
        db.flush()
        student, peer = [
            db.scalar(select(User).where(User.email == f'{account}@asistix.demo'))
            for account in ('estudiante', 'estudiante2')
        ]
        started_at = datetime(2034, 12, 31, 12)
        first, second = first_course.id, second_course.id
        db.add_all(Enrollment(student_id=uid, course_id=course_id, created_at=started_at)
                   for uid, course_id in ((student.id, first), (peer.id, first), (peer.id, second)))
        sessions = [ClassSession(course_id=course_id, started_at=started_at) for course_id in (first, first, first, second)]
        db.add_all(sessions)
        db.flush()
        initial = datetime(2035, 1, 1, 5)
        db.add_all([
            Attendance(student_id=student.id, session_id=sessions[0].id, registered_at=datetime(2035, 1, 1, 4, 59, 59, 999999)),
            Attendance(student_id=student.id, session_id=sessions[1].id, registered_at=initial),
            Attendance(student_id=peer.id, session_id=sessions[1].id, registered_at=initial),
            Attendance(student_id=student.id, session_id=sessions[2].id, registered_at=datetime(2035, 1, 2, 5)),
            Attendance(student_id=peer.id, session_id=sessions[3].id, registered_at=initial),
        ])
        target_session = sessions[1].id
        own_student = student.id
        db.commit()
    return first, second, target_session, own_student


def assert_csv_matches(client, headers, params, records):
    response = client.get(CSV, headers=headers, params=params)
    assert response.status_code == 200
    assert response.content.startswith(b'\xef\xbb\xbf')
    rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
    assert rows[0] == ['Estudiante', 'Materia', 'Sesión', 'Fecha UTC']
    assert rows[1:] == [
        [row['student'], row['course'], str(row['session_id']), row['registered_at']]
        for row in records
    ]


def test_date_filters_csv_parity_and_session_compatibility(client, courses_with_attendance):
    course, _, session_id, _ = courses_with_attendance
    headers = login(client, 'docente')
    tests = [
        ({'course_id': course}, 4),
        ({'course_id': course, 'date_from': '2035-01-01'}, 3),
        ({'course_id': course, 'date_to': '2035-01-01'}, 3),
        ({'course_id': course, 'date_from': '2035-01-01', 'date_to': '2035-01-01'}, 2),
        ({'course_id': course, 'date_from': '2035-01-03'}, 0),
    ]
    for params, count in tests:
        response = client.get(HISTORY, headers=headers, params=params)
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == count
        assert_csv_matches(client, headers, params, rows)
        if count == 2:
            assert all(row['registered_at'] == '2035-01-01T05:00:00Z' for row in rows)
            assert rows[0]['id'] > rows[1]['id']
            assert client.get(HISTORY, headers=headers, params={'session_id': session_id}).json() == rows


def test_scope_is_enforced_for_direct_history_and_csv(client, courses_with_attendance):
    course, foreign, _, student_id = courses_with_attendance
    date_filter = {'date_from': '2035-01-01', 'date_to': '2035-01-01'}
    for endpoint in (HISTORY, CSV):
        for account, forbidden in (('docente', foreign), ('docente2', course), ('estudiante', foreign)):
            headers = login(client, account)
            denied = client.get(endpoint, headers=headers, params={'course_id': forbidden, **date_filter})
            missing = client.get(endpoint, headers=headers, params={'course_id': 99999, **date_filter})
            assert denied.status_code == missing.status_code == 404
            assert denied.json() == missing.json()
    for account, count in (('admin', 3), ('docente', 2), ('docente2', 1), ('estudiante', 1)):
        headers = login(client, account)
        rows = client.get(HISTORY, headers=headers, params=date_filter).json()
        assert len(rows) == count
        if account == 'estudiante':
            assert {row['student_id'] for row in rows} == {student_id}
            own = client.get(HISTORY, headers=headers, params={'course_id': course, **date_filter})
            assert own.json() == rows
        assert_csv_matches(client, headers, date_filter, rows)


@pytest.mark.parametrize('params', [
    {'date_from': '2035-02-30'},
    {'date_from': '2035-01-02', 'date_to': '2035-01-01'},
    {'date_from': '2035-01-01T00:00:00Z'},
    {'date_to': '9999-12-31'},
    {'course_id': 0},
])
def test_invalid_filters(client, params):
    headers = login(client, 'admin')
    for endpoint in (HISTORY, CSV):
        assert client.get(endpoint, headers=headers, params=params).status_code == 422
