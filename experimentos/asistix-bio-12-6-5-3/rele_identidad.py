"""Relay entry point. It receives a connected socket and two ciphertext pipes."""
import json
import os
import msvcrt
from pathlib import Path
import socket
import sys

from comprobar_aislamiento import connect,enter_job,is_appcontainer
from rele_tls import relay


def descriptor(value,mode):
    return os.fdopen(msvcrt.open_osfhandle(int(value),os.O_BINARY),mode)


def assert_denied(path, flags):
    try:
        fd=os.open(path,flags|os.O_BINARY)
    except PermissionError:
        return
    os.close(fd)
    raise RuntimeError('An out-of-scope file could be opened')


def main():
    if not is_appcontainer():
        raise RuntimeError('Relay AppContainer required')
    job=enter_job()
    writer,reader,mode=sys.argv[1:4]
    for path in sys.argv[4:]:
        assert_denied(path,os.O_RDONLY)
        assert_denied(path,os.O_WRONLY)
    outbound_blocked = None if mode=='live' else not any(connect(ip) for ip in ('1.1.1.1','2606:4700:4700::1111'))
    if outbound_blocked is False:
        raise RuntimeError('Relay can initiate outbound connections')
    size=int.from_bytes(sys.stdin.buffer.read(4),'big')
    if not job or not 0<size<=4096:
        raise ValueError('Invalid socket descriptor')
    blob=sys.stdin.buffer.read(size)
    if len(blob)!=size:
        raise ValueError('Incomplete socket descriptor')
    peer=socket.fromshare(blob)
    peer.settimeout(12)
    print(json.dumps({'identity_restricted':True,'file_access_denied':True,'socket_imported':True,'outbound_blocked':outbound_blocked}),flush=True)
    with descriptor(writer,'wb') as to_gateway,descriptor(reader,'rb') as from_gateway:
        relay(peer,to_gateway,from_gateway,lambda _:None)


if __name__=='__main__':
    main()
