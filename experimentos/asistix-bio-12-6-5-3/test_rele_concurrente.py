"""Verification of the opaque relay and two local AppContainers; no real captures."""
import base64
import sys
from contextlib import ExitStack, closing
from concurrent.futures import ThreadPoolExecutor
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
from test_browser_appcontainer import verify_browser
from test_identidad_rele import RELAY, STAGE as RELAY_STAGE, PROFILE as RELAY_PROFILE, launch

GATEWAY=ROOT/'runtime/pilot-gateway/asistix-gateway.exe'
GATEWAY_STAGE=GATEWAY.parent/'sandbox'
PROFILE='ASISTIX.Gateway.Pilot.12652'


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


def main(browser=False):
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
        server.settimeout(.4 if browser else 10)
        port=server.getsockname()[1]
        origin=f'https://127.0.0.1:{port}'
        read_jpeg,send_jpeg=os.pipe()
        read_result,send_result=os.pipe()
        with os.fdopen(read_jpeg,'rb') as face_stdin,os.fdopen(send_result,'wb') as face_stdout:
            with appcontainer_creation():
                face=subprocess.Popen([str(EXECUTABLE),'-B','-I',str(STAGE/'worker_sintetico_ipc.py')],
                                       stdin=face_stdin,stdout=face_stdout,stderr=subprocess.PIPE,close_fds=True)
        try:
            with ExitStack() as pipes:
                lanes=[]
                for _ in range(6):
                    read_client,write_client=os.pipe()
                    read_server,write_server=os.pipe()
                    lanes.append(tuple(pipes.enter_context(os.fdopen(fd,mode)) for fd,mode in (
                        (read_client,'rb'),(write_client,'wb'),(read_server,'rb'),(write_server,'wb'))))
                gateway_ends=[end for in_g,to_g,from_g,out_g in lanes for end in (in_g,out_g)]
                face_handles=(msvcrt.get_osfhandle(send_jpeg),msvcrt.get_osfhandle(read_result))
                lane_handles=tuple(msvcrt.get_osfhandle(end.fileno()) for end in gateway_ends)
                handles=face_handles+lane_handles
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
                    for end in gateway_ends:
                        end.close()
                processes=[]
                failures=[]
                stop_accept=threading.Event()
                denied=(keys/'tls.key',keys/'aes.key',db,GATEWAY_STAGE/'gateway_tls_piloto.py',
                        STAGE/'worker_sintetico_ipc.py',GATEWAY.parent/'python313._pth')
                provision(RELAY,RELAY_STAGE,RELAY_PROFILE)

                def accept():
                    try:
                        for _,to_gateway,from_gateway,_ in lanes:
                            while not stop_accept.is_set():
                                try:
                                    peer=server.accept()[0]
                                except TimeoutError:
                                    if browser:
                                        continue
                                    raise
                                with peer:
                                    processes.append(launch(peer,to_gateway,from_gateway,denied))
                                break
                            to_gateway.close()
                            from_gateway.close()
                    except Exception as error:
                        failures.append(error)

                acceptor=threading.Thread(target=accept,daemon=True)
                acceptor.start()
                def connect():
                    context=ssl.create_default_context(cafile=str(keys/'tls.pem'))
                    return http.client.HTTPSConnection('127.0.0.1',port,context=context,timeout=12)

                try:
                    if browser:
                        public=x509.load_pem_x509_certificate((keys/'tls.pem').read_bytes()).public_key()
                        der=public.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
                        pin=base64.b64encode(hashlib.sha256(der).digest()).decode('ascii')
                        verify_browser(origin,password,ROOT/'runtime',test_spki=pin)
                        assert jpeg not in db.read_bytes()
                        assert {item.name for item in folder.iterdir()}=={'isolated.db'}
                        stop_accept.set()
                    else:
                        with closing(connect()) as primary:
                            primary.request('GET','/')
                            reply=primary.getresponse()
                            assert reply.status==200 and "connect-src 'self'" in reply.headers['Content-Security-Policy']
                            assert b'<video' in reply.read()
                            primary.request('POST','/login',json.dumps({'login':'synthetic-only','password':password}),
                                            {'Origin':origin,'Content-Type':'application/json'})
                            reply=primary.getresponse()
                            assert reply.status==200,reply.status
                            cookie=reply.headers['Set-Cookie'].split(';',1)[0]
                            reply.read()

                            def resource(path):
                                with closing(connect()) as secondary:
                                    secondary.request('GET',path)
                                    response=secondary.getresponse()
                                    assert response.status==200 and response.read()
                            with ThreadPoolExecutor(2) as pool:
                                list(pool.map(resource,('/ui.js','/ui.css')))

                            with closing(connect()) as aborted:
                                aborted.connect()
                                aborted.sock.sendall(f'POST /enrollment HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Length: 1000\r\n\r\npartial'.encode())
                            with closing(store.connect()) as connection:
                                assert connection.execute('SELECT count(*) FROM pilot_templates').fetchone()==(0,)

                            headers={'Origin':origin,'Cookie':cookie}
                            primary.request('POST','/enrollment',jpeg,{
                                **headers,'Content-Type':'image/jpeg','X-Explicit-Consent':'yes','X-Consent-Notice':NOTICE})
                            reply=primary.getresponse()
                            assert reply.status==201 and json.load(reply)['enrolled'],reply.status
                            assert jpeg not in db.read_bytes()
                            assert {item.name for item in folder.iterdir()}=={'isolated.db'}

                        with closing(connect()) as replacement:
                            replacement.request('GET','/enrollment',headers=headers)
                            reply=replacement.getresponse()
                            assert reply.status==200 and json.load(reply)['enrolled']
                            replacement.request('DELETE','/enrollment',headers=headers)
                            reply=replacement.getresponse()
                            assert reply.status==200 and not json.load(reply)['enrolled']
                        with closing(http.client.HTTPSConnection('127.0.0.1',port,context=ssl.create_default_context(),timeout=5)) as untrusted:
                            try:
                                untrusted.connect()
                            except ssl.SSLCertVerificationError:
                                pass
                            else:
                                raise RuntimeError('An untrusted TLS certificate was accepted')
                    acceptor.join(timeout=10)
                    if failures:
                        raise failures[0]
                    assert 1<=len(processes)<=6 if browser else len(processes)==6
                    for relay_process in processes:
                        assert relay_process.wait(timeout=15)==0
                    assert gateway.wait(timeout=15)==0
                    with closing(store.connect()) as connection:
                        assert connection.execute('SELECT count(*) FROM pilot_templates').fetchone()==(0,)
                    if browser:
                        print(f'Chrome por rel? restringido: {len(processes)} conexiones; registro, cierre de c?mara y retiro: OK')
                    else:
                        print('Seis conexiones con rel?s AppContainer, recursos concurrentes, cancelaci?n, reconexi?n, registro y retiro: OK')
                finally:
                    stop_accept.set()
                    for process in (gateway,*processes):
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=5)
                        detail=process.stderr.read()
                        if detail:
                            print(detail.decode(errors='replace')[-2200:].encode('ascii','backslashreplace').decode('ascii'))
                        process.stderr.close()
        finally:
            if face.poll() is None:
                face.kill()
            face.wait(timeout=5)
            face.stderr.close()


if __name__=='__main__':
    main(browser=sys.argv[1:]==['--browser'])
