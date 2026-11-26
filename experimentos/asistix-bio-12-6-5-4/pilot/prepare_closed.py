"""Prepare only the new private pilot, with two fictitious accounts and no templates."""
from contextlib import closing
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess

from pwdlib import PasswordHash

from supervisor_qr import ROOT


HOST = '192.168.100.16'
PRIVATE = Path(os.environ['LOCALAPPDATA']).resolve()/'ASISTIX-Biometric-Pilot-12654'


def prepare():
    source = (ROOT/'backend/asistix-biometria.db').resolve(strict=True)
    if source.stat().st_nlink!=1 or source.parent!=ROOT/'backend':
        raise RuntimeError('Unexpected demonstration database')
    PRIVATE.mkdir(exist_ok=False)
    keys, state = PRIVATE/'keys', PRIVATE/'state'
    keys.mkdir()
    state.mkdir()
    ca=ROOT.parents[1]/'.certs/ca'
    mkcert=ROOT.parent/'mkcert.exe'
    subprocess.run([str(mkcert),'-cert-file',str(keys/'tls.pem'),'-key-file',str(keys/'tls.key'),HOST,'127.0.0.1'],
                   env={**os.environ,'CAROOT':str(ca)},check=True,capture_output=True)
    (keys/'biometric.key').write_bytes(secrets.token_bytes(32))
    (keys/'jwt.secret').write_text(secrets.token_urlsafe(48),encoding='ascii')
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as original:
        with closing(sqlite3.connect(state/'asistix-biometria.db')) as db, db:
            original.backup(db)
            db.execute('PRAGMA secure_delete=ON')
            for table in ('biometric_templates','biometric_session_policy','attendance_challenges','biometric_reviews','biometric_consent_epoch'):
                db.execute(f'DELETE FROM {table}')
            db.execute('UPDATE users SET active=0')
            passwords=PasswordHash.recommended()
            for email in ('docente@asistix.demo','estudiante@asistix.demo'):
                password=secrets.token_urlsafe(18)
                result=db.execute('UPDATE users SET active=1,password_hash=? WHERE email=?',(passwords.hash(password),email))
                if result.rowcount!=1:
                    raise RuntimeError('Expected fictitious user missing')
                print(email,password)
    with closing(sqlite3.connect(state/'revocations.db')) as ledger, ledger:
        ledger.execute('CREATE TABLE active (version TEXT PRIMARY KEY NOT NULL)')


if __name__=='__main__':
    prepare()
