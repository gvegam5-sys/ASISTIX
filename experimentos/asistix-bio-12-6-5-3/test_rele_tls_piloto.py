"""Verification of the opaque relay and two local AppContainers; no real captures."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import hashlib
import http.client
import ipaddress
import json
import msvcrt
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import tempfile
import threading

import cv2
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.x509.oid import NameOID

from appcontainer_piloto import ROOT, EXECUTABLE, STAGE, appcontainer_creation, provision
from registro import NOTICE, Store, password_digest
from rele_tls import relay

GATEWAY=ROOT/'runtime/pilot-gateway/asistix-gateway.exe'
GATEWAY_STAGE=GATEWAY.parent/'sandbox'
PROFILE='ASISTIX.Gateway.Verification.12653'


def cert(folder):
    key=ec.generate_private_key(ec.SECP256R1())
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'ASISTIX synthetic loopback')])
    now=datetime.now(timezone.utc)
    signed=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
            .not_valid_after(now+timedelta(minutes=15))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),False)
            .sign(key,hashes.SHA256()))
    (folder/'tls.pem').write_bytes(signed.public_bytes(serialization.Encoding.PEM))
    (folder/'tls.key').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))


def main():
    source=ROOT/'engine/portrait-a.png'
    assert hashlib.sha256(source.read_bytes()).hexdigest()=='6aa9dd462536a465e5e08cd40e772cfc0d2c7db014055b4f0e2993371604bb82'
    image=cv2.resize(cv2.imread(str(source)),(640,640))
    jpeg=cv2.imencode('.jpg',image)[1].tobytes()
    with tempfile.TemporaryDirectory(dir=ROOT/'runtime') as directory,socket.socket() as server:
        folder,keys=Path(directory)/'state',Path(directory)/'keys'
        folder.mkdir()
        keys.mkdir()
        cert(keys)
        (keys/'aes.key').write_bytes(secrets.token_bytes(32))
        db=folder/'isolated.db'
        db.touch()
        store=Store(db)
        store.prepare()
        salt,password=secrets.token_bytes(16),secrets.token_urlsafe(16)
        with closing(store.connect()) as connection,connection:
            connection.execute('INSERT INTO pilot_accounts(login,salt,password_digest,approved) VALUES(?,?,?,1)',
                               ('synthetic-only',salt,password_digest(password,salt)))
        provision(GATEWAY,GATEWAY_STAGE,PROFILE,writable=folder,readonly=keys)
        server.bind(('127.0.0.1',0))
        server.listen(1)
        server.settimeout(10)
        port=server.getsockname()[1]
        origin=f'https://127.0.0.1:{port}'
        read_jpeg,send_jpeg=os.pipe()
        read_result,send_result=os.pipe()
        with os.fdopen(read_jpeg,'rb') as face_stdin,os.fdopen(send_result,'wb') as face_stdout:
            with appcontainer_creation():
                face=subprocess.Popen([str(EXECUTABLE),'-B','-I',str(STAGE/'worker_sintetico_ipc.py')],
                                       stdin=face_stdin,stdout=face_stdout,stderr=subprocess.PIPE,close_fds=True)
        try:
            handles=(msvcrt.get_osfhandle(send_jpeg),msvcrt.get_osfhandle(read_result))
            for handle in handles:
                os.set_handle_inheritable(handle,True)
            startup=subprocess.STARTUPINFO(lpAttributeList={'handle_list':list(handles)})
            try:
                with appcontainer_creation(GATEWAY,GATEWAY_STAGE,PROFILE,handles):
                    gateway=subprocess.Popen([str(GATEWAY),'-B','-I',str(GATEWAY_STAGE/'gateway_tls_piloto.py'),
                                             str(folder),str(keys),origin,*map(str,handles)],stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,close_fds=True,startupinfo=startup)
            finally:
                os.close(send_jpeg)
                os.close(read_result)
            try:
                transfer=[]
                def serve():
                    peer,_=server.accept()
                    relay(peer,gateway.stdin,gateway.stdout,transfer.append)
                thread=threading.Thread(target=serve,daemon=True)
                thread.start()
                context=ssl.create_default_context(cafile=str(keys/'tls.pem'))
                conn=http.client.HTTPSConnection('127.0.0.1',port,context=context,timeout=20)
                try:
                    conn.request('GET','/')
                    response=conn.getresponse()
                    assert response.status==200 and "connect-src 'self'" in response.headers['Content-Security-Policy']
                    assert b'<video' in response.read()
                    conn.request('POST','/login',body=json.dumps({'login':'synthetic-only','password':password}),
                                 headers={'Origin':origin,'Content-Type':'application/json'})
                    response=conn.getresponse()
                    assert response.status==200,response.status
                    cookie=response.headers['Set-Cookie'].split(';',1)[0]
                    response.read()
                    headers={'Origin':origin,'Cookie':cookie}
                    conn.request('POST','/enrollment',body=jpeg,headers={
                        **headers,'Content-Type':'image/jpeg','X-Explicit-Consent':'yes','X-Consent-Notice':NOTICE})
                    response=conn.getresponse()
                    result=json.load(response)
                    assert response.status==201 and result['enrolled'],response.status
                    assert jpeg not in db.read_bytes()
                    assert {item.name for item in folder.iterdir()}=={'isolated.db'}
                    conn.request('DELETE','/enrollment',headers=headers)
                    response=conn.getresponse()
                    assert response.status==200 and not json.load(response)['enrolled']
                finally:
                    conn.close()
                thread.join(timeout=10)
                gateway.wait(timeout=10)
                assert gateway.returncode==0
                ciphertext=b''.join(transfer)
                assert b'POST /enrollment' not in ciphertext and jpeg[:64] not in ciphertext
                with closing(store.connect()) as connection:
                    assert connection.execute('SELECT count(*) FROM pilot_templates').fetchone()==(0,)
                print('TLS por relay, gateway AppContainer, IPC directo al motor, registro y retiro: OK')
            finally:
                if gateway.poll() is None:
                    gateway.kill()
                gateway.wait(timeout=5)
                diagnostic=gateway.stderr.read()
                if diagnostic:
                    print(diagnostic.decode(errors='replace')[-2200:])
                gateway.stderr.close()
        finally:
            if face.poll() is None:
                face.kill()
            face.wait(timeout=5)
            face.stderr.close()


if __name__=='__main__':
    main()
