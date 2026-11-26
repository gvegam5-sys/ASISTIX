"""Isolated enrollment service. The production entry point keeps uploads disabled."""
import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, closing
from math import isfinite
import hashlib
import hmac
from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit
from pathlib import Path
import secrets
import sqlite3
from threading import Lock
from time import monotonic

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from errores_captura import CaptureError
from comparacion_facial import DEFAULT_THRESHOLD, matches

ROOT = Path(__file__).resolve().parent
NOTICE = 'registro-facial-laboratorio-v1'
MAX_BODY = 384 * 1024
COOKIE = '__Host-asistix-piloto'
MESSAGES = {
    'INVALID':'La captura no es v\u00e1lida. Activa la c\u00e1mara e int\u00e9ntalo otra vez.',
    'NO_FACE':'No detectamos un rostro. Mira hacia la c\u00e1mara.',
    'MULTIPLE':'Debe aparecer una sola persona.',
    'FRAMING':'Posiciona tu rostro dentro del \u00f3valo.',
    'DISTANCE':'Ajusta la distancia hasta encuadrar tu rostro completo.',
    'DARK':'Busca una iluminaci\u00f3n uniforme y evita el contraluz.',
    'BLUR':'Mant\u00e9n el dispositivo y el rostro quietos.',
}


def password_digest(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)


def template_aad(account, version):
    return f'{account}|{version}|{NOTICE}|sface-2021dec'.encode()


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()

    def connect(self):
        db = sqlite3.connect(self.path.as_uri()+'?mode=rw', uri=True, timeout=3)
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA secure_delete=ON')
        return db

    def prepare(self):
        with closing(self.connect()) as db, db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS pilot_accounts (
                id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, salt BLOB NOT NULL,
                password_digest BLOB NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                approved INTEGER NOT NULL CHECK (approved IN (0,1))
            );
            CREATE TABLE IF NOT EXISTS pilot_templates (
                account_id INTEGER PRIMARY KEY REFERENCES pilot_accounts(id), version TEXT UNIQUE NOT NULL,
                notice TEXT NOT NULL, recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                nonce BLOB NOT NULL, ciphertext BLOB NOT NULL
            );
            """)

    def credentials(self, login, password):
        with closing(self.connect()) as db:
            row = db.execute('SELECT id,salt,password_digest,approved FROM pilot_accounts WHERE login=?', (login,)).fetchone()
        digest = password_digest(password, row[1] if row else bytes(16))
        return row[0] if row and hmac.compare_digest(row[2], digest) and row[3] else None

    def state(self, account):
        with closing(self.connect()) as db:
            row = db.execute("""SELECT revision,EXISTS(SELECT 1 FROM pilot_templates WHERE account_id=?)
                                FROM pilot_accounts WHERE id=? AND approved=1""",(account,account)).fetchone()
        if not row:
            raise HTTPException(403,'Cuenta de laboratorio no autorizada.')
        return row

    def verification_template(self, account):
        with closing(self.connect()) as db:
            row = db.execute("""SELECT a.revision, t.version, t.notice, t.nonce, t.ciphertext
                                FROM pilot_accounts a LEFT JOIN pilot_templates t ON t.account_id=a.id
                                WHERE a.id=? AND a.approved=1""", (account,)).fetchone()
        if not row:
            raise HTTPException(403,'Cuenta de laboratorio no autorizada.')
        if row[1] is None or row[2]!=NOTICE:
            raise HTTPException(409,'No tienes un registro facial vigente.')
        return row

    def save(self, account, revision, key, vector):
        identifier = secrets.token_hex(16)
        nonce = secrets.token_bytes(12)
        data = AESGCM(key).encrypt(nonce,vector,template_aad(account,identifier))
        with closing(self.connect()) as db, db:
            updated = db.execute("""UPDATE pilot_accounts SET revision=revision+1
                                    WHERE id=? AND revision=? AND approved=1""", (account,revision))
            if updated.rowcount != 1:
                raise HTTPException(409,'El registro cambi\u00f3. Vuelve a consultar su estado.')
            db.execute('INSERT INTO pilot_templates(account_id,version,notice,nonce,ciphertext) VALUES(?,?,?,?,?)',
                       (account,identifier,NOTICE,nonce,data))

    def revoke(self, account):
        with closing(self.connect()) as db, db:
            db.execute('UPDATE pilot_accounts SET revision=revision+1 WHERE id=?',(account,))
            db.execute('DELETE FROM pilot_templates WHERE account_id=?',(account,))


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    login: str = Field(min_length=1,max_length=100)
    password: str = Field(min_length=1,max_length=200)


CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; "
       "connect-src 'self'; img-src 'self'; media-src 'self'; object-src 'none'; "
       "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


def create_app(store, *, origin, capture_enabled=False, key=None, capture=None, client_network=None, capture_timeout=5, verification_enabled=False,
               verification_threshold=DEFAULT_THRESHOLD):
    target = urlsplit(origin)
    if target.scheme != 'https' or not target.netloc or target.username or target.path or target.query or target.fragment:
        raise ValueError('Se requiere un origen HTTPS exacto.')
    network = ip_network(client_network, strict=True) if client_network else None
    if capture_enabled and (not isinstance(key, bytes) or len(key)!=32 or capture is None):
        raise ValueError('Falta una configuraci\u00f3n de laboratorio aprobada')
    if (verification_enabled and not capture_enabled) or not (
        type(verification_threshold) in (float,int) and isfinite(verification_threshold) and 0 < verification_threshold < 1
    ):
        raise ValueError('Invalid server-only facial verification setting')
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    sessions = OrderedDict()
    last_login = OrderedDict()
    inflight = set()
    attempts = {}
    pool = ThreadPoolExecutor(max_workers=4)
    mutex = Lock()

    @app.middleware('http')
    async def private(request, next_handler):
        address = request.client.host if request.client else ''
        try:
            allowed_peer = network is None or ip_address(address) in network
        except ValueError:
            allowed_peer = False
        if request.url.scheme != 'https' or request.headers.get('host') != target.netloc or not allowed_peer:
            response = JSONResponse({'detail':'Acceso fuera del laboratorio HTTPS autorizado.'},status_code=403)
        elif request.method in ('POST','DELETE') and request.headers.get('origin') != origin:
            response = JSONResponse({'detail':'Origen no autorizado.'}, status_code=403)
        else:
            response = await next_handler(request)
        response.headers.update({
            'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
            'Referrer-Policy':'no-referrer', 'Permissions-Policy':'camera=(self), microphone=()',
            'Content-Security-Policy':CSP,
        })
        return response

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return JSONResponse({'detail':'El laboratorio no pudo completar la operaci\u00f3n.'}, status_code=503,
                            headers={'Cache-Control':'no-store'})

    def account(request):
        token = request.cookies.get(COOKIE,'')
        with mutex:
            entry = sessions.get(token)
        if not entry or entry[1]<monotonic():
            raise HTTPException(401,'Inicia sesi\u00f3n con una cuenta de laboratorio.')
        return entry[0]

    @app.get('/')
    def index():
        return FileResponse(ROOT/'web/index.html')

    @app.get('/ui.js')
    def script():
        return FileResponse(ROOT/'web/ui.js',media_type='text/javascript')

    @app.get('/ui.css')
    def style():
        return FileResponse(ROOT/'web/ui.css',media_type='text/css')

    @app.post('/login')
    async def login(request: Request, response: Response):
        client = request.client.host if request.client else ''
        with mutex:
            now = monotonic()
            if client in last_login and now-last_login[client] < 1:
                raise HTTPException(429,'Espera antes de volver a intentar.')
            last_login[client] = now
            if len(last_login)>128:
                last_login.popitem(last=False)
        try:
            data = Login.model_validate_json(await read_body(request, 1024))
        except ValueError:
            raise HTTPException(400,'Credenciales no v\u00e1lidas.') from None
        uid = await asyncio.to_thread(store.credentials,data.login,data.password)
        if uid is None:
            raise HTTPException(401,'Credenciales o autorizaci\u00f3n no v\u00e1lidas.')
        token = secrets.token_urlsafe(32)
        with mutex:
            sessions.pop(request.cookies.get(COOKIE,''),None)
            sessions[token] = (uid,monotonic()+1800)
            if len(sessions)>128:
                sessions.popitem(last=False)
        response.set_cookie(COOKIE,token,secure=True,httponly=True,samesite='strict',max_age=1800,path='/')
        return {'authenticated':True}

    @app.get('/enrollment')
    def state(request: Request):
        _, enrolled = store.state(account(request))
        return {'enabled':capture_enabled,'enrolled':bool(enrolled),'notice':NOTICE,'verification_enabled':verification_enabled}

    @app.post('/enrollment',status_code=201)
    async def enroll(request: Request):
        uid = account(request)
        if not capture_enabled:
            raise HTTPException(503,'La captura est\u00e1 desactivada hasta completar la revisi\u00f3n de seguridad.')
        if request.headers.get('x-explicit-consent')!='yes' or request.headers.get('x-consent-notice')!=NOTICE:
            raise HTTPException(422,'Debes aceptar el aviso de consentimiento vigente.')
        if request.headers.get('content-type','').lower()!='image/jpeg':
            raise HTTPException(415,MESSAGES['INVALID'])
        revision, enrolled = store.state(uid)
        if enrolled:
            raise HTTPException(409,'Retira primero tu registro vigente.')
        async with inference(uid,request) as vector:
            store.save(uid,revision,key,vector)
        return {'enrolled':True,'message':'¡Registro facial completado correctamente!'}

    @asynccontextmanager
    async def inference(uid,request, *, is_verification=False):
        with mutex:
            if uid in inflight or len(inflight)>=8:
                raise HTTPException(429,'Ya hay una captura en curso o el motor está ocupado.')
            if is_verification:
                now=monotonic()
                recent=[stamp for stamp in attempts.get(uid,[]) if now-stamp<60]
                if len(recent)>=5:
                    raise HTTPException(429,'Espera antes de intentar otra verificación.',headers={'Retry-After':'60'})
                attempts[uid]=recent+[now]
            inflight.add(uid)
        future=None
        try:
            body=await read_body(request,MAX_BODY)
            future=pool.submit(capture,body)
            encoded=await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)),timeout=capture_timeout)
            if len(encoded)!=512:
                raise ValueError('Unexpected template size')
            yield encoded
        except CaptureError as error:
            raise HTTPException(422,MESSAGES.get(str(error),MESSAGES['INVALID'])) from None
        except TimeoutError:
            if future is not None:
                future.cancel()
            raise HTTPException(503,'Se agotó el tiempo de verificación. Inténtalo nuevamente.' if is_verification else
                                'No pudimos procesar la captura. Inténtalo nuevamente.') from None
        except HTTPException:
            raise
        except Exception:
            if future is not None:
                future.cancel()
            raise HTTPException(503,'No fue posible completar la verificación. Inténtalo nuevamente.' if is_verification else
                                'No pudimos procesar la captura. Inténtalo nuevamente.') from None
        finally:
            if future is None or future.done():
                release(uid)
            else:
                future.add_done_callback(lambda _: release(uid))

    @app.post('/verification')
    async def verify(request: Request):
        uid=account(request)
        if not verification_enabled:
            raise HTTPException(503,'La verificación facial está desactivada.')
        if request.url.query or request.headers.get('x-face-verification')!='confirm':
            raise HTTPException(400,'Confirma la verificación desde el laboratorio.')
        if request.headers.get('content-type','').lower()!='image/jpeg':
            raise HTTPException(415,MESSAGES['INVALID'])
        revision,version,_,nonce,cipher=store.verification_template(uid)
        async with inference(uid,request,is_verification=True) as probe:
            # Linearize the comparison with revocation, before decrypting the template.
            with mutex:
                token=request.cookies.get(COOKIE,'')
                session=sessions.get(token)
                if session is None or session[0]!=uid or session[1]<=monotonic():
                    raise HTTPException(401,'Inicia sesión nuevamente.')
                if store.verification_template(uid)!=(revision,version,NOTICE,nonce,cipher):
                    raise HTTPException(409,'El registro facial cambió. Inicia otra verificación.')
                try:
                    reference=AESGCM(key).decrypt(nonce,cipher,template_aad(uid,version))
                    matched=matches(reference,probe,verification_threshold)
                except (InvalidTag,TypeError,ValueError):
                    raise HTTPException(503,'No fue posible completar la verificación.') from None
                finally:
                    reference=None
                return {'matched':matched, 'message':(
                    'Verificación facial completada correctamente.' if matched else
                    'El rostro capturado no coincide con el registro.')}

    def release(uid):
        with mutex:
            inflight.discard(uid)

    @app.delete('/enrollment')
    def revoke(request: Request):
        uid = account(request)
        with mutex:
            store.state(uid)
            store.revoke(uid)
        return {'enrolled':False}

    return app


async def read_body(request, maximum):
    content = bytearray()
    try:
        async with asyncio.timeout(6):
            async for chunk in request.stream():
                if len(content)+len(chunk)>maximum:
                    raise HTTPException(413,'La solicitud excede el tama\u00f1o permitido.')
                content.extend(chunk)
    except TimeoutError:
        raise HTTPException(408,'Se agot\u00f3 el tiempo de carga.') from None
    return bytes(content)


# Deliberate activation gate. This entry point accepts no real enrollment.
app = create_app(Store(ROOT/'runtime/asistix-bio-piloto.db'),origin='https://192.168.100.16:5188')
