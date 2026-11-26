"""Restricted HTTPS terminator for the academic QR pilot. Control pipe carries descriptor metadata only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import itertools
import json
import os
from pathlib import Path
import ssl
import sys
from threading import Event, Lock

from comprobar_aislamiento import enter_job, is_appcontainer
from gateway_transport import channel, serve_lane
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
                if code in {'INVALID','DARK','NO_FACE','MULTIPLE','FRAMING','DISTANCE','BLUR'}:
                    raise CaptureError(code)
            if len(vector)!=512:
                raise RuntimeError('Worker did not return a template')
            return vector
        finally:
            with lock:
                waiting.pop(identifier,None)

    if mode not in ('closed','voluntary-authorized'):
        raise RuntimeError('Unknown academic gateway mode')
    private=folder.parent
    if (private.name!='ASISTIX-Biometric-Pilot-12654' or not private.is_absolute()
            or private.parent.name.lower()!='local' or private.parent.parent.name.lower()!='appdata'
            or folder!=private/'state' or keys!=private/'keys'):
        raise RuntimeError('Wrong private state directory')
    files=[folder/'asistix-biometria.db',folder/'revocations.db',keys/'jwt.secret',keys/'biometric.key',
           keys/'tls.pem',keys/'tls.key']
    if any(not path.is_file() or path.resolve()!=path or path.stat().st_nlink!=1 for path in files):
        raise RuntimeError('Invalid private state files')
    os.environ.update(ASISTIX_PHYSICAL_GATEWAY='12654', ASISTIX_PRIVATE_PILOT_ROOT=str(private),
                      DEMO_MODE='true', BIOMETRIC_LAB='true',
                      DATABASE_URL='sqlite:///'+files[0].as_posix(),
                      JWT_SECRET=files[2].read_text(encoding='ascii').strip(), BIOMETRIC_KEY_FILE=str(files[3]),
                      CORS_ORIGINS=origin)
    from sqlalchemy import select
    from app.biometric_schema import migrations
    from app.db import SessionLocal
    from app.models import User
    from app.physical_gateway import build_gateway
    with SessionLocal() as db:
        if db.scalar(select(migrations.c.version).where(migrations.c.version==1)) != 1:
            raise RuntimeError('Private schema is not migrated')
        students=db.scalars(select(User.id).where(User.role=='student',User.active.is_(True))).all()
        if len(students)!=1:
            raise RuntimeError('Exactly one enabled volunteer account is required')
    app=build_gateway(origin=origin,worker_capture=capture,web_root=Path(__file__).parent/'web',
                      student_id=students[0],armed=mode=='voluntary-authorized')

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
