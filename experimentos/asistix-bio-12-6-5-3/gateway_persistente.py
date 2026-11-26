"""Persistent synthetic gateway. Control pipe carries descriptor metadata only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import itertools
import json
from pathlib import Path
import ssl
import sys
from threading import Event, Lock

from comprobar_aislamiento import enter_job, is_appcontainer
from gateway_tls_piloto import channel, serve_lane
from registro import MESSAGES, Store, create_app
from errores_captura import CaptureError


def main():
    if not is_appcontainer():
        raise RuntimeError('Gateway AppContainer required')
    job=enter_job()
    folder,keys,origin,mode=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],sys.argv[4]
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version=ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(keys/'tls.pem',keys/'tls.key')
    waiting={}
    lock=Lock()
    sequence=itertools.count()

    def notify(payload):
        with lock:
            print(json.dumps(payload),flush=True)

    def capture(jpeg):
        ready=Event()
        reply={}
        with lock:
            identifier=next(sequence)
            waiting[identifier]=(ready,reply)
        try:
            notify({'op':'face','id':identifier})
            if not ready.wait(3) or 'handles' not in reply:
                raise RuntimeError('Worker allocation failed')
            read_handle,write_handle=reply['handles']
            with channel(write_handle,'wb') as outgoing, channel(read_handle,'rb') as incoming:
                outgoing.write(len(jpeg).to_bytes(4,'big')+jpeg)
                outgoing.flush()
                outgoing.close()
                vector=incoming.read(513)
            if vector.startswith(b'QUALITY:') and len(vector)<32:
                code=vector[8:].decode('ascii')
                if code in MESSAGES:
                    raise CaptureError(code)
            if len(vector)!=512:
                raise RuntimeError('Worker did not return a template')
            return vector
        finally:
            with lock:
                waiting.pop(identifier,None)

    enabled=mode in ('synthetic','voluntary-authorized')
    app=create_app(Store(folder/'isolated.db'),origin=origin,capture_enabled=enabled,verification_enabled=enabled,
                   key=(keys/'aes.key').read_bytes(),capture=capture,client_network='127.0.0.1/32',capture_timeout=9)
    fixture=Path(__file__).resolve().parent/'test-portrait.png'
    if mode=='synthetic' and fixture.is_file():
        from fastapi.responses import FileResponse
        @app.get('/synthetic-fixture')
        def synthetic_fixture():
            return FileResponse(fixture,media_type='image/png')

    def lane(identifier, handles):
        try:
            with channel(handles[0],'rb') as incoming,channel(handles[1],'wb') as outgoing:
                serve_lane(app,tls,incoming,outgoing)
        except (EOFError,OSError,ValueError):
            pass
        finally:
            notify({'op':'closed','id':identifier})

    notify({'op':'ready'})
    with ThreadPoolExecutor(max_workers=12) as pool:
        while job:
            raw=sys.stdin.buffer.readline(1025)
            if not raw or len(raw)>1024:
                break
            command=json.loads(raw)
            if command['op']=='lane':
                pool.submit(lane,command['id'],command['handles'])
            elif command['op']=='face':
                identifier=command['id']
                with lock:
                    slot=waiting.get(identifier)
                    if slot:
                        slot[1].update(command)
                        slot[0].set()
                if not slot and 'handles' in command:
                    with channel(command['handles'][0],'rb'),channel(command['handles'][1],'wb'):
                        pass
            elif command['op']=='stop':
                break
            else:
                raise RuntimeError('Unexpected control frame')


if __name__=='__main__':
    main()
