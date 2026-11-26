from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import hashlib
from math import sqrt
from pathlib import Path
import secrets
import tempfile
from threading import Event
import unittest

import cv2
import numpy as np
from fastapi.testclient import TestClient

from comparacion_facial import DEFAULT_THRESHOLD,FORMAT,matches
from errores_captura import CaptureError
from motor import FacialEngine
from registro import ROOT,NOTICE,Store,create_app,password_digest

ORIGIN='https://pilot.example'
HEAD={'Origin':ORIGIN,'Content-Type':'image/jpeg','X-Face-Verification':'confirm'}
ENROLL={**HEAD,'X-Explicit-Consent':'yes','X-Consent-Notice':NOTICE}


def vec(a,b):
    return FORMAT.pack(a,b,*([0]*126))


class Verification(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(dir=ROOT/'runtime')
        self.addCleanup(tmp.cleanup)
        self.db=Path(tmp.name)/'case.db'
        self.db.touch()
        self.store=Store(self.db)
        self.store.prepare()
        self.secret=secrets.token_bytes(32)
        self.password=secrets.token_urlsafe(18)
        self.mode=lambda _:vec(1,0)
        for name in ('alpha','beta'):
            salt=secrets.token_bytes(16)
            with closing(self.store.connect()) as conn,conn:
                conn.execute('INSERT INTO pilot_accounts(login,salt,password_digest,approved) VALUES(?,?,?,1)',
                             (name,salt,password_digest(self.password,salt)))
        self.app=create_app(self.store,origin=ORIGIN,capture_enabled=True,verification_enabled=True,
                            key=self.secret,capture=lambda image:self.mode(image),capture_timeout=.9)

    def client(self,name='alpha',peer='127.0.0.1',app=None):
        client=TestClient(app or self.app,base_url=ORIGIN,client=(peer,50000))
        self.addCleanup(client.close)
        if name:
            assert client.post('/login',headers={'Origin':ORIGIN},json={'login':name,'password':self.password}).status_code==200
        return client

    def enroll(self,client,body=b'synthetic'):
        self.assertEqual(client.post('/enrollment',headers=ENROLL,content=body).status_code,201)

    def test_cosine_boundary_and_bad_vectors(self):
        low, high=DEFAULT_THRESHOLD-.001,DEFAULT_THRESHOLD+.001
        self.assertFalse(matches(vec(1,0),vec(low,sqrt(1-low*low)),DEFAULT_THRESHOLD))
        self.assertTrue(matches(vec(1,0),vec(high,sqrt(1-high*high)),DEFAULT_THRESHOLD))
        self.assertTrue(matches(vec(1,0),vec(1,0),1))
        for sample in (b'short',vec(0,0),vec(float('nan'),0),vec(float('inf'),0)):
            with self.assertRaises(ValueError):
                matches(vec(1,0),sample,DEFAULT_THRESHOLD)

    def test_access_identity_and_server_only_threshold(self):
        a,b=self.client(),self.client('beta','127.0.0.2')
        self.assertEqual(self.client(None).post('/verification',headers=HEAD,content=b'x').status_code,401)
        self.assertEqual(a.post('/verification',headers=HEAD,content=b'x').status_code,409)
        self.enroll(a)
        self.assertEqual(b.post('/verification?account_id=1&threshold=0',headers=HEAD,content=b'x').status_code,400)
        self.assertEqual(b.post('/verification',headers={**HEAD,'X-Account-ID':'1'},content=b'x').status_code,409)
        self.mode=lambda _:vec(0,1)
        self.enroll(b)
        response=a.post('/verification',headers={**HEAD,'X-Threshold':'0'},content=b'x')
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json()['matched'])
        self.assertEqual(set(response.json()),{'message','matched'})
        self.assertTrue(b.post('/verification',headers=HEAD,content=b'x').json()['matched'])
        self.assertEqual(a.post('/verification',headers={**HEAD,'Origin':'https://wrong.example'},content=b'x').status_code,403)

    def test_corruption_and_revocation(self):
        client=self.client()
        self.enroll(client)
        with closing(self.store.connect()) as db,db:
            db.execute('UPDATE pilot_templates SET ciphertext=?',(b'corrupt',))
        response=client.post('/verification',headers=HEAD,content=b'x')
        self.assertEqual(response.status_code,503)
        self.assertNotIn('matched',response.json())
        self.assertEqual(client.delete('/enrollment',headers={'Origin':ORIGIN}).status_code,200)
        self.assertEqual(client.post('/verification',headers=HEAD,content=b'x').status_code,409)

    def test_duplicates_and_revocation_while_processing(self):
        client=self.client()
        self.enroll(client)
        started,finish=Event(),Event()
        def blocked(_):
            started.set()
            finish.wait(.7)
            return vec(1,0)
        self.mode=blocked
        with ThreadPoolExecutor(1) as pool:
            pending=pool.submit(client.post,'/verification',headers=HEAD,content=b'x')
            try:
                self.assertTrue(started.wait(.5))
                self.assertEqual(client.post('/verification',headers=HEAD,content=b'x').status_code,429)
                self.assertEqual(client.delete('/enrollment',headers={'Origin':ORIGIN}).status_code,200)
            finally:
                finish.set()
            response=pending.result()
        self.assertEqual(response.status_code,409)
        self.assertNotIn('matched',response.json())

    def test_quality_messages(self):
        a,b=self.client(),self.client('beta','127.0.0.2')
        self.enroll(a)
        self.enroll(b)
        def failure(code):
            def capture(_):
                raise CaptureError(code)
            return capture
        for i,code in enumerate(('NO_FACE','MULTIPLE','DARK','BLUR','FRAMING','DISTANCE')):
            self.mode=failure(code)
            response=(a if i<4 else b).post('/verification',headers=HEAD,content=b'x')
            self.assertEqual(response.status_code,422)
            self.assertNotIn('matched',response.json())

    def test_worker_timeout_recovery_and_attempt_cap(self):
        from time import sleep
        client=self.client()
        self.enroll(client)
        def stalled(_):
            sleep(1.02)
            return vec(1,0)
        self.mode=stalled
        timed=client.post('/verification',headers=HEAD,content=b'x')
        self.assertEqual(timed.status_code,503)
        sleep(.2)
        def fail(_):
            raise RuntimeError('internal-only detail')
        self.mode=fail
        broken=client.post('/verification',headers=HEAD,content=b'x')
        self.assertEqual(broken.status_code,503)
        self.assertNotIn('internal-only',broken.text)
        self.mode=lambda _:vec(1,0)
        for _ in range(3):
            self.assertTrue(client.post('/verification',headers=HEAD,content=b'x').json()['matched'])
        limited=client.post('/verification',headers=HEAD,content=b'x')
        self.assertEqual(limited.status_code,429)
        self.assertIn('Retry-After',limited.headers)

    def test_real_engine_synthetic_jpeg_and_no_persistence(self):
        engine=FacialEngine()
        self.mode=engine.capture
        def image(name,digest):
            path=ROOT/'engine'/name
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
            return cv2.resize(cv2.imread(str(path)),(640,640))
        def jpeg(array):
            return cv2.imencode('.jpg',array)[1].tobytes()
        a=image('portrait-a.png','6aa9dd462536a465e5e08cd40e772cfc0d2c7db014055b4f0e2993371604bb82')
        b=image('portrait-b.png','cfbc2e01cd75ae434cc2f319dd7a73c2f2c3f1fc6c0caac4b8a4c144b59fe05c')
        client=self.client()
        self.enroll(client,jpeg(a))
        before=self.db.read_bytes()
        similar=jpeg(cv2.convertScaleAbs(a,alpha=.92,beta=8))
        other=jpeg(b)
        self.assertTrue(client.post('/verification',headers=HEAD,content=similar).json()['matched'])
        self.assertFalse(client.post('/verification',headers=HEAD,content=other).json()['matched'])
        self.assertEqual(client.post('/verification',headers=HEAD,content=jpeg(np.full_like(a,128))).status_code,422)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertNotIn(similar,before)
        self.assertNotIn(other,before)
        self.assertEqual({p.name for p in self.db.parent.iterdir()},{'case.db'})
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='attendance'").fetchone(),(0,))

    def test_default_disabled(self):
        client=self.client(app=create_app(self.store,origin=ORIGIN))
        self.assertFalse(client.get('/enrollment').json()['verification_enabled'])
        self.assertEqual(client.post('/verification',headers=HEAD,content=b'x').status_code,503)


if __name__=='__main__':
    unittest.main()
