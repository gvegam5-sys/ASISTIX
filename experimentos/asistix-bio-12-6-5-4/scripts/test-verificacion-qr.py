"""End-to-end API check for 12.6.5.4, with a disposable seeded SQLite copy."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import json
import os
import secrets
import sqlite3
import sys
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

root = Path(__file__).resolve().parents[1]
backend = root / 'backend'
source = backend / 'asistix-biometria.db'
sys.path.insert(0, str(backend))
os.environ.update(DATABASE_URL='sqlite:///'+source.as_posix(), JWT_SECRET=secrets.token_urlsafe(48),
                  DEMO_MODE='true', BIOMETRIC_LAB='true')

from app import biometric_attendance as bio
from app.biometric_schema import metadata
from app.db import Base, get_db
from app.main import app
from app.models import Attendance, User
from app.security import sign


def run(folder):
    disposable = folder / 'integration.db'
    engine = create_engine('sqlite:///'+disposable.as_posix(), poolclass=NullPool)
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as db, closing(sqlite3.connect(disposable)) as copy:
        db.backup(copy)
    Base.metadata.create_all(engine)
    metadata.create_all(engine)
    sessions = sessionmaker(engine)
    ledger = folder / 'revocations.db'
    with closing(sqlite3.connect(ledger)) as db, db:
        db.execute('CREATE TABLE active (version TEXT PRIMARY KEY NOT NULL)')
    bio.open_revocations = lambda: sqlite3.connect(ledger)
    key = secrets.token_bytes(32)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    bio.crypt = lambda: AESGCM(key)

    def dependency():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    client = TestClient(app)
    with sessions() as db:
        ids = {name: db.scalar(select(User.id).where(User.email==name+'@asistix.demo'))
               for name in ('docente','estudiante','estudiante2','estudiante3')}
    def call(method, path, who, body=None, status=200, code=None):
        headers = {'Authorization':'Bearer '+sign({'sub':str(ids[who]),'kind':'access'})}
        response = client.request(method, path, headers=headers, json=body)
        assert response.status_code in (status if isinstance(status,tuple) else (status,)), (path,response.status_code,response.text)
        result=response.json()
        if code:
            assert result.get('code')==code, result
        return response.status_code, result

    teacher, student, other = 'docente','estudiante','estudiante2'
    sid = call('POST','/courses/1/sessions',teacher,status=201)[1]['id']
    session = f'/sessions/{sid}'
    call('PUT',session+'/biometric',teacher)
    def qr():
        return {'token':call('GET',session+'/qr',teacher)[1]['token']}
    def issue():
        return call('POST','/biometric/challenges',student,qr(),status=201)[1]
    def confirm(challenge,fixture,who=student,status=201,code=None):
        return call('POST',f'/biometric/challenges/{challenge}/confirm',who,{'fixture':fixture},status,code)
    call('POST','/attendance',student,qr(),409,'BIOMETRIC_REQUIRED')
    assert issue()['enrolled'] is False
    good=bio.assigned_fixture(ids[student])
    bad='b' if good=='a' else 'a'
    consent={'explicit':True,'notice':bio.NOTICE}
    call('POST','/biometric/enrollment',student,consent,201)
    challenge=issue()['challenge']
    confirm(challenge,good,other,409,'CHALLENGE_INVALID')
    confirm(challenge,bad,status=409,code='BIOMETRIC_MISMATCH')
    call('DELETE','/biometric/enrollment',student)
    confirm(challenge,good,status=409,code='CHALLENGE_INVALID')
    call('POST','/biometric/enrollment',student,consent,201)
    challenge=issue()['challenge']
    call('DELETE',f'/biometric/challenges/{challenge}',student)
    confirm(challenge,good,status=409,code='CHALLENGE_INVALID')
    challenge=issue()['challenge']
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _: confirm(challenge,good,status=(201,409))[0],range(2)))
    assert sorted(results)==[201,409]
    confirm(challenge,good,status=409)
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Attendance).where(Attendance.session_id==sid))==1
    call('DELETE','/biometric/enrollment',student)
    call('POST',session+'/close',teacher)

    # Test the gated JPEG contract with synthetic images and the real isolated worker.
    import cv2
    from app.isolated_fixture_inference import IsolatedFixtureEngine, PILOT
    fixture_engine = IsolatedFixtureEngine()
    def jpeg(fixture):
        image = cv2.imread(str(PILOT/'engine'/f'portrait-{fixture}.png'))
        return cv2.imencode('.jpg', cv2.resize(image, (640, 640)))[1].tobytes()
    origin = 'https://pilot.invalid'
    raw = TestClient(app, base_url=origin)
    def send_jpeg(path, frame, status, *, actor=student, explicit=True, peer=origin):
        headers = {'Authorization':'Bearer '+sign({'sub':str(ids[actor]),'kind':'access'}),
                   'Origin':peer, 'Content-Type':'image/jpeg'}
        if explicit:
            headers.update({'X-Explicit-Consent':'yes','X-Consent-Notice':bio.PHYSICAL_NOTICE})
        response = raw.post(path, headers=headers, content=frame)
        assert response.status_code==status, (status,response.status_code,response.text)
        return response.json()
    enrollment = '/biometric/physical/enrollment'
    good, bad = jpeg(good), jpeg(bad)
    send_jpeg(enrollment,good,404)
    app.state.physical_origin = origin
    app.state.physical_student_id = ids[student]
    def capture_synthetic(_account, frame):
        return fixture_engine.infer_frame(frame)
    app.state.isolated_physical_capture = capture_synthetic
    send_jpeg(enrollment,good,404,actor=other)
    send_jpeg(enrollment,good,404,peer='https://other.invalid')
    send_jpeg(enrollment,good,422,explicit=False)
    send_jpeg(enrollment,b'not a jpeg',422)
    def revoked_during_capture(account, frame):
        call('DELETE','/biometric/enrollment',student)
        return capture_synthetic(account,frame)
    app.state.isolated_physical_capture = revoked_during_capture
    assert send_jpeg(enrollment,good,409)['code']=='BIOMETRIC_TEMPLATE_CHANGED'
    app.state.isolated_physical_capture = capture_synthetic
    send_jpeg(enrollment,good,201)
    sid = call('POST','/courses/1/sessions',teacher,status=201)[1]['id']
    session = f'/sessions/{sid}'
    call('PUT',session+'/biometric',teacher)
    challenge = issue()['challenge']
    path = f'/biometric/physical/challenges/{challenge}/confirm'
    assert send_jpeg(path,bad,409)['code']=='BIOMETRIC_MISMATCH'
    call('DELETE',session+'/biometric',student,status=403)
    call('DELETE',session+'/biometric',teacher)
    assert send_jpeg(path,good,409)['code']=='CHALLENGE_INVALID'
    call('POST','/attendance',other,qr(),201)
    call('PUT',session+'/biometric',teacher)
    challenge = issue()['challenge']
    path = f'/biometric/physical/challenges/{challenge}/confirm'
    send_jpeg(path,good,201)
    send_jpeg(path,good,409)
    review=call('POST','/biometric/reviews','estudiante3',{'session_id':sid,'reason':'no_consent'},202)[1]
    call('POST',f"/biometric/reviews/{review['id']}/approve",'estudiante3',status=403)
    call('POST',f"/biometric/reviews/{review['id']}/approve",teacher)
    call('DELETE','/biometric/enrollment',student)
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Attendance).where(Attendance.session_id==sid))==3
        assert not bio.current_template(db, ids[student])
    app.state.isolated_physical_capture = None
    print(json.dumps({'qr_only_blocked':True,'not_enrolled':True,'other_identity_blocked':True,'mismatch':True,
                      'revocation':True,'cancel':True,'concurrent_statuses':results,'attendances':1,
                      'jpeg_gate':True,'explicit_consent':True,'teacher_toggle':True,'qr_normal':True,
                      'jpeg_1to1':True,'jpeg_replay_rejected':True,'enrollment_revocation_race':True,'teacher_review':True}))
    engine.dispose()


if __name__=='__main__':
    with TemporaryDirectory(dir=root) as temporary:
        run(Path(temporary))
