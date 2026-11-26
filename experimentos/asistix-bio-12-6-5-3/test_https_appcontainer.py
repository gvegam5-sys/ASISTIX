"""Ephemeral loopback HTTPS -> FastAPI -> AppContainer. Synthetic data only."""
from contextlib import closing
import hashlib
import http.client
from ipaddress import ip_address
import sys
import json
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import tempfile
import threading
import time

import cv2
import uvicorn
from fastapi.responses import FileResponse
from test_browser_appcontainer import verify_browser

from appcontainer_piloto import EXECUTABLE, STAGE, appcontainer_creation
from registro import ROOT, NOTICE, Store, create_app, password_digest


def install_test_network_guard():
    """Limit Python sockets in this disposable process to local test traffic."""
    events = {'socket.connect','socket.bind','socket.sendto'}
    def loopback(host):
        try:
            return ip_address(host).is_loopback
        except (TypeError,ValueError):
            return False
    def guard(event,args):
        if event in events:
            address = args[-1]
            if not isinstance(address,tuple) or not loopback(address[0]):
                raise PermissionError('Synthetic test prohibits external sockets')
        if event == 'socket.getaddrinfo' and not loopback(args[0]):
            raise PermissionError('Synthetic test prohibits external DNS resolution')
    sys.addaudithook(guard)
    for family,destination in ((socket.AF_INET,('1.1.1.1',443)),
                               (socket.AF_INET6,('2606:4700:4700::1111',443))):
        with socket.socket(family,socket.SOCK_STREAM) as probe:
            try:
                probe.connect(destination)
            except PermissionError:
                pass
            else:
                raise RuntimeError('Synthetic socket audit guard did not block egress')


def main():
    install_test_network_guard()
    fixture = ROOT/'engine/portrait-a.png'
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == '6aa9dd462536a465e5e08cd40e772cfc0d2c7db014055b4f0e2993371604bb82'
    image = cv2.resize(cv2.imread(str(fixture)),(640,640))
    jpeg = cv2.imencode('.jpg',image)[1].tobytes()
    certificates = ROOT.parents[1]/'.certs'

    def process(capture):
        with appcontainer_creation():
            result = subprocess.run([str(EXECUTABLE),'-B','-I',str(STAGE/'worker_sintetico_ipc.py')],
                                    input=len(capture).to_bytes(4,'big')+capture,
                                    capture_output=True,timeout=5,check=True,close_fds=True)
        assert len(result.stdout)==512
        return result.stdout

    with tempfile.TemporaryDirectory(dir=ROOT/'runtime') as folder, socket.socket() as listener:
        path = Path(folder)/'test.db'
        path.touch()
        store = Store(path)
        store.prepare()
        password,salt = secrets.token_urlsafe(16),secrets.token_bytes(16)
        with closing(store.connect()) as db, db:
            db.execute('INSERT INTO pilot_accounts(login,salt,password_digest,approved) VALUES (?,?,?,1)',
                       ('synthetic-only',salt,password_digest(password,salt)))
        listener.bind(('127.0.0.1',0))
        port = listener.getsockname()[1]
        origin = f'https://127.0.0.1:{port}'
        app = create_app(store,origin=origin,capture_enabled=True,key=secrets.token_bytes(32),capture=process,client_network='127.0.0.1/32')
        @app.get('/synthetic-fixture')
        def synthetic_fixture():
            return FileResponse(fixture,media_type='image/png')

        config = uvicorn.Config(app,host='127.0.0.1',access_log=False,log_level='critical',proxy_headers=False,timeout_graceful_shutdown=3,
                                ssl_certfile=str(certificates/'asistix.pem'),ssl_keyfile=str(certificates/'asistix-key.pem'))
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(.05)
            assert server.started
            context = ssl.create_default_context(cafile=str(certificates/'ca/rootCA.pem'))
            conn = http.client.HTTPSConnection('127.0.0.1',port,context=context,timeout=15)
            try:
                conn.request('GET','/')
                page = conn.getresponse()
                assert page.status==200 and "connect-src 'self'" in page.headers['Content-Security-Policy']
                assert b'<video' in page.read()
                conn.request('GET','/ui.js')
                script = conn.getresponse()
                assert script.status==200 and b'getUserMedia' in script.read()
                conn.request('POST','/login',body=json.dumps({'login':'synthetic-only','password':password}),
                             headers={'Origin':origin,'Content-Type':'application/json'})
                response = conn.getresponse()
                assert response.status==200
                cookie = response.headers['Set-Cookie'].split(';',1)[0]
                response.read()
                endpoint_headers={'Origin':origin,'Cookie':cookie}
                conn.request('POST','/enrollment',body=jpeg,headers={
                    **endpoint_headers,'Content-Type':'image/jpeg','X-Explicit-Consent':'yes','X-Consent-Notice':NOTICE})
                response = conn.getresponse()
                data = json.load(response)
                assert response.status==201 and data['enrolled'] and response.headers['Cache-Control']=='no-store',response.status
                assert jpeg not in path.read_bytes()
                assert set(item.name for item in Path(folder).iterdir())=={'test.db'}
                conn.request('DELETE','/enrollment',headers=endpoint_headers)
                response = conn.getresponse()
                assert response.status==200 and not json.load(response)['enrolled']
                with closing(store.connect()) as db:
                    assert db.execute('SELECT count(*) FROM pilot_templates').fetchone()==(0,)
            finally:
                conn.close()
            verify_browser(origin,password,ROOT/'runtime')
            with closing(store.connect()) as db:
                assert db.execute('SELECT count(*) FROM pilot_templates').fetchone()==(0,)
            assert set(item.name for item in Path(folder).iterdir())=={'test.db'}
        finally:
            server.should_exit=True
            thread.join(timeout=10)
        assert not thread.is_alive()
    print('Navegador sintético, HTTPS con CA verificada, IPC, registro sintético cifrado y eliminación: OK.')


if __name__=='__main__':
    main()
