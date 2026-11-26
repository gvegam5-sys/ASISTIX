"""PostgreSQL races using API requests and independent real database transactions."""
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from math import ceil
from threading import Barrier
import json
import time

import pytest
from sqlalchemy import event, select, text

from app.db import SessionLocal, engine
from app.models import Attendance, Audit, ClassSession, Course, Enrollment, QRToken, Student, User, now
from app.security import decode, sign
from test_flow import assert_error, login, start

pytestmark = pytest.mark.skipif(engine.dialect.name != 'postgresql', reason='Requires row locks in PostgreSQL')


def parallel(requests: list[Callable], locked_row=None):
    barrier = Barrier(len(requests) + 1)

    def send(request):
        barrier.wait(10)
        started = time.perf_counter()
        response = request()
        return response, (time.perf_counter() - started) * 1000

    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        with SessionLocal() as blocker, engine.connect().execution_options(isolation_level='AUTOCOMMIT') as observer:
            if locked_row is not None:
                blocker.execute(locked_row.with_for_update()).scalar_one()
            futures = [pool.submit(send, request) for request in requests]
            barrier.wait(10)
            waiting = 0
            if locked_row is not None:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    waiting = observer.scalar(text("""
                        SELECT count(*) FROM pg_stat_activity
                        WHERE datname = current_database()
                          AND pid <> pg_backend_pid() AND wait_event_type = 'Lock'
                    """))
                    if waiting >= 2:
                        break
                    time.sleep(.02)
            blocker.rollback()
        results = [future.result(timeout=30) for future in futures]
    if locked_row is not None:
        assert waiting >= 2, 'Requests did not overlap at the PostgreSQL row lock'
    return results, waiting


def audit_matches(sid, expected):
    with SessionLocal() as db:
        students = list(db.scalars(select(Attendance.student_id).where(Attendance.session_id == sid)))
        actors = list(db.scalars(select(Audit.actor_id).where(Audit.action == f'attendance:{sid}')))
    assert len(students) == len(set(students)) == expected
    assert Counter(actors) == Counter(students)


def lock_session(sid):
    return select(ClassSession).where(ClassSession.id == sid)


def test_parallel_session_opening(client):
    teacher = login(client, 'docente')
    call = lambda: client.post('/courses/1/sessions', headers=teacher)
    responses, _ = parallel([call, call], select(Course).where(Course.id == 1))
    assert sorted(r.status_code for r, _ in responses) == [201, 409]
    with SessionLocal() as db:
        assert len(list(db.scalars(select(ClassSession).where(
            ClassSession.course_id == 1, ClassSession.closed_at.is_(None))))) == 1
        assert len(list(db.scalars(select(Audit.id).where(Audit.action == 'start_session:1')))) == 1


@pytest.mark.parametrize('different', [False, True])
def test_parallel_attendance(client, different):
    teacher = login(client, 'docente')
    first = login(client, 'estudiante')
    second = login(client, 'estudiante2') if different else first
    sid, token = start(client, teacher)
    responses, _ = parallel([
        lambda: client.post('/attendance', json={'token': token}, headers=first),
        lambda: client.post('/attendance', json={'token': token}, headers=second),
    ], lock_session(sid))
    assert sorted(r.status_code for r, _ in responses) == ([201, 201] if different else [201, 409])
    if not different:
        assert_error(next(r for r, _ in responses if r.status_code == 409), 409, 'ATTENDANCE_DUPLICATE')
    audit_matches(sid, 2 if different else 1)


def test_parallel_issue_and_renewal(client):
    sid = client.post('/courses/1/sessions', headers=login(client, 'docente')).json()['id']
    teacher = login(client, 'docente')
    call = lambda: client.get(f'/sessions/{sid}/qr', headers=teacher)
    ids = []
    for _ in range(2):
        responses, _ = parallel([call, call], lock_session(sid))
        assert [r.status_code for r, _ in responses] == [200, 200]
        issued = {decode(r.json()['token'], 'qr')['jti'] for r, _ in responses}
        assert len(issued) == 1
        ids.append(issued.pop())
        with SessionLocal() as db:
            token = db.get(QRToken, ids[-1])
            token.expires_at = now()
            db.commit()
    assert ids[0] != ids[1]
    with SessionLocal() as db:
        assert set(db.scalars(select(QRToken.id).where(QRToken.session_id == sid))) == set(ids)


def test_scan_races_with_close(client):
    teacher = login(client, 'docente')
    student = login(client, 'estudiante')
    sid, token = start(client, teacher)
    results, _ = parallel([
        lambda: client.post('/attendance', headers=student, json={'token': token}),
        lambda: client.post(f'/sessions/{sid}/close', headers=teacher),
    ], lock_session(sid))
    scan, close = [r for r, _ in results]
    assert close.status_code == 200
    if scan.status_code != 201:
        assert_error(scan, 409, 'CLASS_CLOSED')
    audit_matches(sid, int(scan.status_code == 201))
    with SessionLocal() as db:
        assert db.get(ClassSession, sid).closed_at is not None
        assert len(list(db.scalars(select(Audit.id).where(Audit.action == f'close_session:{sid}')))) == 1


def test_mismatched_and_expired_tokens_leave_no_writes(client):
    teacher = login(client, 'docente')
    student = login(client, 'estudiante')
    sid, token = start(client, teacher)
    other = client.post('/courses/2/sessions', headers=teacher).json()['id']
    claims = decode(token, 'qr')
    mismatch = sign({'kind': 'qr', 'jti': claims['jti'], 'sid': other})
    assert_error(client.post('/attendance', headers=student, json={'token': mismatch}), 400, 'QR_INVALID')
    with SessionLocal() as db:
        stored = db.get(QRToken, claims['jti'])
        stored.expires_at = now()
        db.commit()
    assert_error(client.post('/attendance', headers=student, json={'token': token}), 400, 'QR_EXPIRED')
    audit_matches(sid, 0)
    audit_matches(other, 0)


def test_audit_failure_rolls_back_attendance(client, monkeypatch):
    from app import main

    teacher = login(client, 'docente')
    student = login(client, 'estudiante')
    sid, token = start(client, teacher)
    original = main.audit

    def fail_attendance_audit(db, user, action):
        if action == f'attendance:{sid}':
            db.add(Audit(actor_id=-1, action=action))
        else:
            original(db, user, action)

    monkeypatch.setattr(main, 'audit', fail_attendance_audit)
    assert_error(client.post('/attendance', headers=student, json={'token': token}), 503, 'ATTENDANCE_UNAVAILABLE')
    audit_matches(sid, 0)
    monkeypatch.setattr(main, 'audit', original)
    assert client.post('/attendance', headers=student, json={'token': token}).status_code == 201
    audit_matches(sid, 1)


def load_students(size):
    with SessionLocal() as db:
        ids = []
        for i in range(size):
            u = User(name=f'Load {i}', email=f'load{i}@asistix.demo', password_hash='unused-test-login', role='student')
            db.add(u)
            db.flush()
            db.add(Student(user_id=u.id, code=f'LOAD-{i}'))
            db.flush()
            db.add(Enrollment(student_id=u.id, course_id=1))
            ids.append(u.id)
        db.commit()
    return ids


@pytest.mark.parametrize('size', [10, 25, 50])
def test_parallel_student_load(client, size):
    teacher = login(client, 'docente')
    ids = load_students(size)
    sid, token = start(client, teacher)

    def request(user_id):
        headers = {'Authorization': 'Bearer ' + sign({'kind': 'access', 'sub': str(user_id)})}
        return lambda: client.post('/attendance', headers=headers, json={'token': token})

    results, waiting = parallel([request(user_id) for user_id in ids], lock_session(sid))
    status = Counter(r.status_code for r, _ in results)
    ms = sorted(latency for _, latency in results)
    print('MEASUREMENT', json.dumps({
        'requests': size, 'statuses': dict(status), 'p50_ms': round(ms[ceil(size * .5) - 1], 2),
        'p95_ms': round(ms[ceil(size * .95) - 1], 2), 'max_ms': round(ms[-1], 2),
        'lock_waiters_at_release': waiting,
    }), flush=True)
    assert status == {201: size}
    audit_matches(sid, size)


def test_query_plans_on_demo(client):
    teacher = login(client, 'docente')
    queries = {}

    def capture(conn, cursor, statement, parameters, context, executemany):
        if 'ORDER BY attendance.registered_at DESC' in statement:
            queries['history'] = (statement, parameters)
        if 'LEFT OUTER JOIN class_sessions' in statement and 'LEFT OUTER JOIN attendance' in statement:
            queries['absenteeism'] = (statement, parameters)

    with engine.begin() as conn:
        conn.exec_driver_sql('ANALYZE attendance, class_sessions, enrollments, courses, users')
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        assert client.get('/attendance', headers=teacher).status_code == 200
        assert client.get('/dashboard', headers=teacher).status_code == 200
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert set(queries) == {'history', 'absenteeism'}
    with engine.connect() as conn:
        for name, (query, parameters) in queries.items():
            result = conn.exec_driver_sql('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + query, parameters).scalar_one()[0]
            nodes = []
            pending = [result['Plan']]
            while pending:
                node = pending.pop()
                nodes.append(node['Node Type'] + (': ' + node['Relation Name'] if 'Relation Name' in node else ''))
                pending.extend(node.get('Plans', []))
            print('QUERY_PLAN', json.dumps({'query': name, 'nodes': nodes,
                                           'rows': result['Plan']['Actual Rows'], 'execution_ms': result['Execution Time']}), flush=True)
