"""Check the voluntary account. Read the password without echo or persistence."""
from contextlib import closing
import getpass
import http.client
import json
import os
from pathlib import Path
import sqlite3
import ssl

origin='https://192.168.100.16:5188'
password=getpass.getpass('Pilot password: ')
ctx=ssl.create_default_context(cafile='.certs/ca/rootCA.pem')
with closing(http.client.HTTPSConnection('192.168.100.16',5188,context=ctx,timeout=10)) as connection:
    connection.request('POST','/login',json.dumps({'login':'estudiante-piloto','password':password}),
                       {'Origin':origin,'Content-Type':'application/json'})
    response=connection.getresponse()
    assert response.status==200,response.status
    cookie=response.headers['Set-Cookie']
    assert all(flag.lower() in cookie.lower() for flag in ('Secure','HttpOnly','SameSite=strict'))
    response.read()
    headers={'Cookie':cookie.split(';',1)[0],'Origin':origin}
    connection.request('GET','/enrollment',headers=headers)
    response=connection.getresponse()
    state=json.load(response)
    assert response.status==200 and state['enabled'] and not state['enrolled']
    connection.request('POST','/enrollment',b'',{**headers,'Content-Type':'image/jpeg'})
    response=connection.getresponse()
    assert response.status==422
    response.read()
    connection.request('POST','/enrollment',b'',{**headers,'Origin':'https://unauthorized.invalid','Content-Type':'image/jpeg'})
    response=connection.getresponse()
    assert response.status==403
    response.read()
    connection.request('DELETE','/enrollment',headers=headers)
    response=connection.getresponse()
    assert response.status==200 and not json.load(response)['enrolled']
db=Path(os.environ['LOCALAPPDATA'])/'ASISTIX-Biometric-Pilot-12652/state/isolated.db'
with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
    assert connection.execute('pragma integrity_check').fetchall()==[('ok',)]
    assert connection.execute('SELECT login FROM pilot_accounts').fetchall()==[('estudiante-piloto',)]
    assert connection.execute('SELECT count(*) FROM pilot_templates').fetchone()==(0,)
    assert connection.execute("SELECT count(*) FROM sqlite_master WHERE name='attendance'").fetchone()==(0,)
print('Authentication, consent requirement, origin restriction, revocation and empty template store: OK.')
