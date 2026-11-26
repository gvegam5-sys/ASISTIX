"""Launcher for the individual pilot. Do not run until its scoped Wi-Fi rule is authorized."""
import argparse
from contextlib import closing
from ipaddress import ip_address,ip_network
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

from cryptography import x509
from registro import ROOT,Store,password_digest
from supervisor_piloto import Supervisor

NAME='estudiante-piloto'
HOST='192.168.100.16'
PORT=5188
RULE='ASISTIX-Pilot-12653-WiFi-HTTPS'
OUTBOUND_RULE='ASISTIX-Pilot-12653-Block-External'


def check_rule():
    worker=ROOT/'runtime/pilot-python/asistix-face.exe'
    command=f"""$ErrorActionPreference='Stop'
$r=Get-NetFirewallRule -PolicyStore ActiveStore -Name '{RULE}'
$b=Get-NetFirewallRule -PolicyStore ActiveStore -Name '{OUTBOUND_RULE}'
$bf=$b | Get-NetFirewallApplicationFilter
$ba=$b | Get-NetFirewallAddressFilter
if(@($b).Count -ne 1 -or $b.Enabled -ne 'True' -or $b.Direction -ne 'Outbound' -or $b.Action -ne 'Block' -or
   $b.Profile -ne 'Any' -or $bf.Program -ne '{worker}' -or $ba.RemoteAddress -ne 'Any'){{exit 4}}
$ip=Get-NetIPAddress -InterfaceAlias 'Wi-Fi' -AddressFamily IPv4 -IPAddress '{HOST}'
if($ip.PrefixLength -ne 24 -or (Get-NetConnectionProfile -InterfaceIndex $ip.InterfaceIndex).NetworkCategory -ne 'Public'){{exit 5}}
$f=$r | Get-NetFirewallApplicationFilter
$p=$r | Get-NetFirewallPortFilter
$a=$r | Get-NetFirewallAddressFilter
$i=$r | Get-NetFirewallInterfaceFilter
if(@($r).Count -ne 1 -or $r.Enabled -ne 'True' -or $r.Direction -ne 'Inbound' -or $r.Action -ne 'Allow' -or
   $r.EdgeTraversalPolicy -ne 'Block' -or $p.Protocol -notin @('TCP',6) -or
   $r.Profile -ne 'Public' -or $f.Program -ne '{sys.executable}' -or $p.LocalPort -ne '5188' -or
   @($i.InterfaceAlias).Count -ne 1 -or @($i.InterfaceAlias)[0] -ne 'Wi-Fi' -or
   @($a.LocalAddress).Count -ne 1 -or @($a.LocalAddress)[0] -ne '{HOST}' -or @($a.RemoteAddress).Count -ne 1 -or
   @($a.RemoteAddress)[0] -notin @('192.168.100.0/24','192.168.100.0/255.255.255.0')){{exit 3}}"""
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],
                          capture_output=True,timeout=10)
    if result.returncode:
        raise RuntimeError('The authorized Wi-Fi rule could not be verified')


def setup(directory):
    state,keys=directory/'state',directory/'keys'
    for folder in (directory,state,keys):
        if folder.exists() and folder.resolve()!=folder:
            raise RuntimeError('Private pilot path is redirected')
        folder.mkdir(exist_ok=True)
    db=state/'isolated.db'
    if any((state/name).exists() for name in ('isolated.db-wal','isolated.db-shm')) or db.exists():
        raise RuntimeError('Pilot already provisioned; use start to preserve data')
    ca=ROOT.parents[1]/'.certs/ca'
    if not all((ca/name).is_file() for name in ('rootCA.pem','rootCA-key.pem')):
        raise RuntimeError('Existing pilot CA was not found')
    mkcert=ROOT.parents[1]/'tools/mkcert.exe'
    subprocess.run([str(mkcert),'-cert-file',str(keys/'tls.pem'),'-key-file',str(keys/'tls.key'),HOST,'127.0.0.1'],
                   env={**os.environ,'CAROOT':str(ca)},cwd=ROOT,check=True,capture_output=True)
    (keys/'aes.key').write_bytes(secrets.token_bytes(32))
    db.touch(exist_ok=False)
    store=Store(db)
    store.prepare()
    salt,password=secrets.token_bytes(16),secrets.token_urlsafe(18)
    with closing(store.connect()) as connection,connection:
        connection.execute('INSERT INTO pilot_accounts(login,salt,password_digest,approved) VALUES(?,?,?,1)',
                           (NAME,salt,password_digest(password,salt)))
    print(f'Cuenta ficticia: {NAME}\nClave de un solo suministro: {password}',flush=True)
    return state,keys


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','start'])
    args=parser.parse_args()
    expected=ROOT/'runtime/pilot-supervisor/asistix-supervisor.exe'
    if not Path(sys.executable).samefile(expected):
        raise RuntimeError('Use the dedicated supervisor executable')
    check_rule()
    with socket.socket() as probe:
        probe.bind((HOST,0))
    directory=Path(os.environ['LOCALAPPDATA']).resolve()/'ASISTIX-Biometric-Pilot-12653'
    if directory.is_relative_to(ROOT.parents[1]):
        raise RuntimeError('Private pilot state cannot be provisioned in the workspace')
    if args.action=='prepare':
        setup(directory)
        return
    state,keys=directory/'state',directory/'keys'
    db=state/'isolated.db'
    for path in (directory,state,keys,db,*(keys/name for name in ('tls.pem','tls.key','aes.key'))):
        if not path.exists() or path.resolve()!=path or (path.is_file() and path.stat().st_nlink!=1):
            raise RuntimeError('Invalid private pilot file layout')
    with closing(Store(db).connect()) as connection:
        authorized=connection.execute('SELECT login FROM pilot_accounts WHERE approved=1').fetchall()
    if authorized != [(NAME,)]:
        raise RuntimeError('The voluntary pilot is disabled; no authorized pilot account.')
    certificate=x509.load_pem_x509_certificate((keys/'tls.pem').read_bytes())
    names=certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    if ip_address(HOST) not in names.get_values_for_type(x509.IPAddress):
        raise RuntimeError('The pilot certificate does not cover the authorized address')
    with Supervisor(state,keys,host=HOST,port=PORT,network=str(ip_network(HOST+'/24',strict=False)),backend_port=8014,physical_authorized=True) as supervisor:
        print('Solo la red local autorizada puede acceder a',supervisor.origin,flush=True)
        try:
            while supervisor.gateway.poll() is None:
                time.sleep(.5)
        except KeyboardInterrupt:
            pass


if __name__=='__main__':
    main()
