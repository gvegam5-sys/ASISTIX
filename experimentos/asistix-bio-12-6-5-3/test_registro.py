from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets
import sqlite3
import tempfile
from threading import Event
import unittest

import cv2
import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient

from motor import CaptureError, FacialEngine, jpeg_size
from registro import COOKIE, NOTICE, ROOT, Store, create_app, password_digest

ORIGIN = 'https://pilot.example'
HEADERS = {'Origin':ORIGIN, 'X-Explicit-Consent':'yes','X-Consent-Notice':NOTICE,'Content-Type':'image/jpeg'}


class Registration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'runtime')
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'test.db'
        self.path.touch()
        self.store=Store(self.path)
        self.store.prepare()
        self.key=secrets.token_bytes(32)
        self.password=secrets.token_urlsafe(18)
        self.vector=bytes(range(256))*2
        self.mode=lambda _:self.vector
        with closing(self.store.connect()) as db, db:
            for name, approved in [('student',1),('unapproved',0)]:
                salt=secrets.token_bytes(16)
                db.execute('INSERT INTO pilot_accounts(login,salt,password_digest,approved) VALUES(?,?,?,?)',
                           (name,salt,password_digest(self.password,salt),approved))

    def client(self, enabled=True, user='student'):
        app=create_app(self.store,origin=ORIGIN,capture_enabled=enabled,key=self.key,capture=lambda b:self.mode(b))
        client=TestClient(app,base_url=ORIGIN)
        self.addCleanup(client.close)
        if user:
            result=client.post('/login',headers={'Origin':ORIGIN},json={'login':user,'password':self.password})
            self.assertEqual(result.status_code,200 if user=='student' else 401)
        return client

    def submit(self, client, headers=HEADERS, data=b'synthetic'):
        return client.post('/enrollment',headers=headers,content=data)

    def test_permissions_and_default(self):
        anon=self.client(user=None)
        self.assertEqual(self.submit(anon).status_code,401)
        self.assertEqual(self.submit(self.client(user='unapproved')).status_code,401)
        disabled=self.client(enabled=False)
        self.assertEqual(self.submit(disabled).status_code,503)
        self.assertFalse(disabled.get('/enrollment').json()['enabled'])
        self.assertEqual(disabled.get('/attendance').status_code,404)

    def test_requires_consent_origin_and_bounds(self):
        client=self.client()
        self.assertEqual(self.submit(client,{**HEADERS,'X-Explicit-Consent':'no'}).status_code,422)
        self.assertEqual(self.submit(client,{**HEADERS,'X-Consent-Notice':'old'}).status_code,422)
        self.assertEqual(self.submit(client,{**HEADERS,'Origin':'https://other.example'}).status_code,403)
        self.assertEqual(self.submit(client,{**HEADERS,'Content-Type':'image/png'}).status_code,415)
        self.assertEqual(self.submit(client,data=bytes(400000)).status_code,413)

    def test_limits_hosts_schemes_and_peer_addresses(self):
        app=create_app(self.store,origin=ORIGIN,client_network='192.168.100.8/32')
        with TestClient(app,base_url=ORIGIN,client=('192.168.100.8',50000)) as client:
            self.assertEqual(client.get('/').status_code,200)
            self.assertEqual(client.get('/',headers={'Host':'outside.example'}).status_code,403)
            self.assertEqual(client.get('http://pilot.example/').status_code,403)
        with TestClient(app,base_url=ORIGIN,client=('192.168.100.9',50000)) as other:
            self.assertEqual(other.get('/',headers={'X-Forwarded-For':'192.168.100.8'}).status_code,403)

    def test_encryption_and_delete(self):
        client=self.client()
        self.assertEqual(self.submit(client).status_code,201)
        self.assertEqual(self.submit(client).status_code,409)
        self.assertTrue(client.get('/enrollment').json()['enrolled'])
        with closing(self.store.connect()) as db:
            account, version, nonce, ciphertext=db.execute('SELECT account_id,version,nonce,ciphertext FROM pilot_templates').fetchone()
        self.assertNotEqual(ciphertext,self.vector)
        self.assertEqual(AESGCM(self.key).decrypt(nonce,ciphertext,f'{account}|{version}|{NOTICE}|sface-2021dec'.encode()),self.vector)
        self.assertEqual(client.delete('/enrollment',headers={'Origin':ORIGIN}).json(),{'enrolled':False})
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pilot_templates').fetchone(),(0,))
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='attendance'").fetchone(),(0,))

    def test_synthetic_enrollment_full_http_flow(self):
        client = self.client()
        self.mode = FacialEngine().capture
        fixture = ROOT / 'engine/portrait-a.png'
        image = cv2.imdecode(np.frombuffer(fixture.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        jpeg = cv2.imencode('.jpg',cv2.resize(image,(640,640)))[1].tobytes()
        result = self.submit(client,data=jpeg)
        self.assertEqual(result.status_code,201)
        self.assertTrue(result.json()['enrolled'])
        self.assertEqual(result.headers['cache-control'],'no-store')
        self.assertIn("connect-src 'self'",result.headers['content-security-policy'])
        self.assertEqual(set(p.name for p in self.path.parent.iterdir()),{'test.db'})
        self.assertNotIn(jpeg,self.path.read_bytes())
        self.assertEqual(client.delete('/enrollment',headers={'Origin':ORIGIN}).status_code,200)
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pilot_templates').fetchone(),(0,))
        self.assertEqual(set(p.name for p in self.path.parent.iterdir()),{'test.db'})

    def test_motor_errors(self):
        client=self.client()
        def reject(code):
            def run(_):
                raise CaptureError(code)
            return run
        for code in ('INVALID','NO_FACE','MULTIPLE','FRAMING','DISTANCE','DARK','BLUR'):
            self.mode=reject(code)
            response=self.submit(client)
            self.assertEqual(response.status_code,422)
            self.assertNotIn(code,response.text)
        self.mode=lambda _:None
        self.assertEqual(self.submit(client).status_code,503)
        self.assertFalse(client.get('/enrollment').json()['enrolled'])

    def test_concurrent_request_and_revocation_during_inference(self):
        client=self.client()
        started, finish=Event(), Event()
        def capture(_):
            started.set()
            finish.wait(2)
            return self.vector
        self.mode=capture
        with ThreadPoolExecutor(1) as pool:
            pending=pool.submit(self.submit,client)
            try:
                self.assertTrue(started.wait(2))
                self.assertEqual(self.submit(client).status_code,429)
                self.assertEqual(client.delete('/enrollment',headers={'Origin':ORIGIN}).status_code,200)
            finally:
                finish.set()
            self.assertEqual(pending.result().status_code,409)
        self.assertFalse(client.get('/enrollment').json()['enrolled'])


class RealMotorSyntheticInput(unittest.TestCase):
    def test_capture_quality(self):
        first=cv2.imdecode(np.frombuffer((ROOT/'engine/portrait-a.png').read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        first=cv2.resize(first,(640,640))
        engine=FacialEngine()
        def jpeg(image):
            return cv2.imencode('.jpg',image)[1].tobytes()
        self.assertEqual(jpeg_size(jpeg(first)),(640,640))
        self.assertEqual(len(engine.capture(jpeg(first))),512)
        tiles=np.full_like(first,128)
        tiles[160:480,:320]=cv2.resize(first,(320,320))
        tiles[160:480,320:]=tiles[160:480,:320]
        for data,expected in [(b'invalid','INVALID'),(jpeg(np.full_like(first,128)),'NO_FACE'),
                              (jpeg(tiles),'MULTIPLE'),(jpeg(np.full_like(first,12)),'DARK'),
                              (jpeg(np.empty((1400,1400,3),dtype=np.uint8)),'INVALID')]:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(CaptureError,expected):
                    engine.capture(data)


if __name__=='__main__':
    unittest.main()
