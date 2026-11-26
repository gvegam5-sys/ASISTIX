from datetime import date, datetime

import pytest
from sqlalchemy import select

from test_flow import client, login
from app import main
from app.db import SessionLocal
from app.models import Attendance, ClassSession, User
from app.reporting_time import reporting_day_bounds


def test_guayaquil_day_bounds():
    assert reporting_day_bounds(date(2035, 1, 1)) == (
        datetime(2035, 1, 1, 5),
        datetime(2035, 1, 2, 5),
    )


@pytest.mark.parametrize(('account', 'expected'), [('admin', 8), ('docente', 8), ('estudiante', 1)])
def test_dashboard_midnight_week_rollover_and_role_scope(client, monkeypatch, account, expected):
    headers = login(client, account)
    before_midnight = datetime(2035, 1, 1, 4, 59, 59, 999999)
    midnight = datetime(2035, 1, 1, 5)
    with SessionLocal() as db:
        students = list(db.scalars(select(User).where(User.role == 'student').order_by(User.id)))
        old = ClassSession(course_id=1, started_at=datetime(2034, 12, 25, 12), closed_at=datetime(2034, 12, 25, 13))
        crossing = ClassSession(course_id=1, started_at=datetime(2035, 1, 1, 4, 30), closed_at=datetime(2035, 1, 1, 5, 5))
        opened = ClassSession(course_id=2, started_at=midnight)
        db.add_all([old, crossing, opened])
        db.flush()
        db.add_all([
            Attendance(student_id=students[0].id, session_id=crossing.id, registered_at=before_midnight),
            Attendance(student_id=students[0].id, session_id=opened.id, registered_at=midnight),
            Attendance(student_id=students[1].id, session_id=opened.id, registered_at=midnight),
        ])
        db.commit()

    # Inspect the midnight boundary after the crossing session is closed in the fixture.
    monkeypatch.setattr(main, 'now', lambda: before_midnight)
    sunday_response = client.get('/dashboard', headers=headers)
    assert sunday_response.status_code == 200
    sunday = sunday_response.json()
    assert sunday['timezone'] == 'America/Guayaquil'
    assert sunday['local_date'] == '2034-12-31'
    assert sunday['today'] == 1
    assert [p['date'] for p in sunday['week']] == [f'2034-12-{d}' for d in range(25, 32)]
    assert sunday['week'][0] == {'date': '2034-12-25', 'present': 0, 'expected': expected}
    assert sunday['week'][-1] == {'date': '2034-12-31', 'present': 1, 'expected': expected}

    monkeypatch.setattr(main, 'now', lambda: midnight)
    monday_response = client.get('/dashboard', headers=headers)
    assert monday_response.status_code == 200
    monday = monday_response.json()
    assert monday['local_date'] == '2035-01-01'
    assert monday['today'] == (1 if account == 'estudiante' else 2)
    assert monday['week'][:-1] == sunday['week'][1:]
    assert monday['week'][-1] == {'date': '2035-01-01', 'present': 0, 'expected': 0}
    for key in ('courses', 'rate', 'absent_rate'):
        assert monday[key] == sunday[key]
    records = client.get('/attendance', headers=headers).json()
    assert any(row['registered_at'] == '2035-01-01T05:00:00Z' for row in records)
