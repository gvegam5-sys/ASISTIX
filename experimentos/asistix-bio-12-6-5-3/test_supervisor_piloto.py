"""Stability integration suite; no real media, devices or pilot data."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import ssl
import tempfile
import time

import cv2
import numpy as np
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from appcontainer_piloto import ROOT
from motor import FacialEngine
from registro import NOTICE, Store,password_digest
from supervisor_piloto import Supervisor
from test_browser_appcontainer import verify_browser
from test_rele_tls_piloto import cert


def main():
    cycles=int(os.environ.get('ASISTIX_SYNTHETIC_CYCLES','50'))
    portraits=[]
    for name,digest in (('portrait-a.png','6aa9dd462536a465e5e08cd40e772cfc0d2c7db014055b4f0e2993371604bb82'),
                        ('portrait-b.png','cfbc2e01cd75ae434cc2f319dd7a73c2f2c3f1fc6c0caac4b8a4c144b59fe05c')):
        path=ROOT/'engine'/name
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
        portraits.append(cv2.imencode('.jpg',cv2.resize(cv2.imread(str(path)),(640,640)))[1].tobytes())
    engine=FacialEngine()
    expected=[np.frombuffer(engine.capture(image),dtype='>f4') for image in portraits]
    assert not np.allclose(*expected)
    with tempfile.TemporaryDirectory(dir=ROOT/'runtime') as temporary:
        data,keys=Path(temporary)/'state',Path(temporary)/'keys'
        data.mkdir();keys.mkdir()
        cert(keys)
        secret=secrets.token_bytes(32)
        (keys/'aes.key').write_bytes(secret)
        path=data/'isolated.db'
        path.touch()
        store=Store(path)
        store.prepare()
        credentials={f'synthetic-{i}':secrets.token_urlsafe(16) for i in range(9)}
        credentials['synthetic-only']=secrets.token_urlsafe(16)
        with closing(store.connect()) as db,db:
            for login,password in credentials.items():
                salt=secrets.token_bytes(16)
                db.execute('INSERT INTO pilot_accounts(login,salt,password_digest,approved) VALUES (?,?,?,1)',
                           (login,salt,password_digest(password,salt)))
        ctx=ssl.create_default_context(cafile=str(keys/'tls.pem'))
        timings=[]
        with Supervisor(data,keys) as supervisor:
            def connect():
                return http.client.HTTPSConnection('127.0.0.1',supervisor.port,context=ctx,timeout=20)

            def call(connection,method,url,*,body=None,headers=None):
                connection.request(method,url,body,headers or {})
                reply=connection.getresponse()
                result=reply.read()
                return reply.status,result,{name.lower(): value for name,value in reply.getheaders()}

            def login(connection,name):
                status,_,headers=call(connection,'POST','/login',body=json.dumps({'login':name,'password':credentials[name]}),
                                      headers={'Origin':supervisor.origin,'Content-Type':'application/json'})
                assert status==200,status
                return {'Origin':supervisor.origin,'Cookie':headers['set-cookie'].split(';',1)[0]}

            def submit(connection,auth,image):
                start=time.perf_counter()
                status,_,_=call(connection,'POST','/enrollment',body=image,headers={
                    **auth,'Content-Type':'image/jpeg','X-Explicit-Consent':'yes','X-Consent-Notice':NOTICE})
                timings.append((time.perf_counter()-start)*1000)
                return status

            with closing(connect()) as client:
                status,body,_=call(client,'GET','/?utm_source=chatgpt.com')
                assert status==200 and b'Registro facial' in body
                plain=call(client,'GET','/')
                assert plain[0]==200 and plain[1]==body
                assert call(client,'GET','/ui.js?cache=v1')[0]==200
                assert call(client,'GET','/enrollment?x=1')[0]==401
                assert call(client,'POST','/login?skip=1',body=b'{}')[0]==400
                assert call(client,'GET','//other.example/')[0]==400
                auth=login(client,'synthetic-0')
                for index in range(cycles):
                    sample=index%2
                    assert submit(client,auth,portraits[sample])==201,index
                    with closing(store.connect()) as db:
                        owner,version,nonce,cipher=db.execute('SELECT account_id,version,nonce,ciphertext FROM pilot_templates').fetchone()
                    plaintext=AESGCM(secret).decrypt(nonce,cipher,f'{owner}|{version}|{NOTICE}|sface-2021dec'.encode())
                    assert np.allclose(np.frombuffer(plaintext,dtype='>f4'),expected[sample],rtol=1e-4,atol=1e-6),index
                    if index == 0:
                        verify_headers={**auth,'Content-Type':'image/jpeg','X-Face-Verification':'confirm'}
                        code,result,_=call(client,'POST','/verification',body=portraits[sample],headers=verify_headers)
                        assert code==200 and json.loads(result)['matched']
                        code,result,_=call(client,'POST','/verification',body=portraits[1-sample],headers=verify_headers)
                        assert code==200 and not json.loads(result)['matched']
                        assert call(client,'POST','/verification',body=b'not-jpeg',headers=verify_headers)[0]==422
                    assert call(client,'DELETE','/enrollment',headers=auth)[0]==200,index
                assert call(client,'POST','/verification',body=portraits[0],headers=verify_headers)[0]==409
                assert submit(client,auth,b'invalid-synthetic-jpeg')==422
                assert submit(client,auth,portraits[1])==201
                assert call(client,'DELETE','/enrollment',headers=auth)[0]==200
            with closing(connect()) as cancelled:
                cancelled.connect()
                cancelled.sock.sendall(f'POST /enrollment HTTP/1.1\r\nHost: 127.0.0.1:{supervisor.port}\r\nContent-Length: 2000\r\n\r\npart'.encode())
            with closing(connect()) as replacement:
                status,body,_=call(replacement,'GET','/enrollment',headers=auth)
                assert status==200 and not json.loads(body)['enrolled']

            auths=[auth]
            for i in range(1,9):
                time.sleep(1.02)
                with closing(connect()) as client:
                    auths.append(login(client,f'synthetic-{i}'))
            from threading import Barrier
            barrier=Barrier(9)
            def concurrent(i):
                with closing(connect()) as client:
                    client.connect()
                    barrier.wait(timeout=12)
                    return submit(client,auths[i],portraits[i%2])
            with ThreadPoolExecutor(9) as pool:
                results=list(pool.map(concurrent,range(9)))
            assert results.count(201)==8 and results.count(429)==1, (results, [round(t) for t in timings[-9:]])
            for credentials_row in auths:
                with closing(connect()) as client:
                    assert call(client,'DELETE','/enrollment',headers=credentials_row)[0]==200
            key=x509.load_pem_x509_certificate((keys/'tls.pem').read_bytes()).public_key()
            der=key.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
            pin=base64.b64encode(hashlib.sha256(der).digest()).decode('ascii')
            verify_browser(supervisor.origin,credentials['synthetic-only'],ROOT/'runtime',test_spki=pin)
            with closing(store.connect()) as db:
                assert db.execute('SELECT count(*) FROM pilot_templates').fetchone()==(0,)
                assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='attendance'").fetchone()==(0,)
            assert set(f.name for f in data.iterdir())=={'isolated.db'}
            assert all(jpeg not in path.read_bytes() for jpeg in portraits)
        assert not supervisor.errors,supervisor.errors
        import _winapi
        alive=[]
        for pid in supervisor.started_pids:
            try: handle=_winapi.OpenProcess(0x100000,False,pid)
            except OSError: continue
            try:
                if _winapi.WaitForSingleObject(handle,0)==258: alive.append(pid)
            finally: _winapi.CloseHandle(handle)
        assert not alive,alive
        print(json.dumps({'sequential_inferences':cycles,'enrollment_revocation_cycles':cycles,
                          'concurrent_results':results,'peak_active_workers':supervisor.high_workers,
                          'p50_ms':round(float(np.median(timings)),1),'p95_ms':round(float(np.percentile(timings,95)),1),
                          'tracked_processes':len(supervisor.started_pids),'orphans':len(alive),'browser':True}))


if __name__=='__main__':
    main()
