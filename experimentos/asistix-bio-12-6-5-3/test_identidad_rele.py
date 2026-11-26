"""Loopback test: accepted socket delegated to a named relay AppContainer."""
import json
import msvcrt
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading

from appcontainer_piloto import ROOT,appcontainer_creation,provision
from comprobar_aislamiento import connect

RELAY=ROOT/'runtime/pilot-relay/asistix-relay.exe'
STAGE=RELAY.parent/'sandbox'
PROFILE='ASISTIX.Relay.Verification.12653'


def launch(peer, writer, reader, denied, *, check_egress=True):
    handles=(msvcrt.get_osfhandle(writer.fileno()),msvcrt.get_osfhandle(reader.fileno()))
    for handle in handles:
        os.set_handle_inheritable(handle,True)
    startup=subprocess.STARTUPINFO(lpAttributeList={'handle_list':list(handles)})
    try:
        with appcontainer_creation(RELAY,STAGE,PROFILE,handles):
            process=subprocess.Popen([str(RELAY),'-B','-I',str(STAGE/'rele_identidad.py'),*map(str,handles),'probe' if check_egress else 'live',*map(str,denied)],
                                     stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                     close_fds=True,startupinfo=startup)
    finally:
        for handle in handles:
            os.set_handle_inheritable(handle,False)
    try:
        encoded=peer.share(process.pid)
        process.stdin.write(len(encoded).to_bytes(4,'big')+encoded)
        process.stdin.close()
        def cancel_unresponsive_relay():
            if process.poll() is None:
                process.kill()
        timer=threading.Timer(8,cancel_unresponsive_relay)
        timer.start()
        try:
            result=process.stdout.readline(1025)
        finally:
            timer.cancel()
            timer.join()
        if not result:
            raise RuntimeError(process.stderr.read().decode(errors='replace')[-2400:])
        assert json.loads(result)=={'identity_restricted':True,'file_access_denied':True,'socket_imported':True,'outbound_blocked':True if check_egress else None}
        return process
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        raise


def main():
    assert all(connect(ip) for ip in ('1.1.1.1','2606:4700:4700::1111')), 'Positive control failed'
    provision(RELAY,STAGE,PROFILE)
    with tempfile.TemporaryDirectory(dir=ROOT/'runtime') as directory,socket.socket() as server:
        folder=Path(directory)
        denied=[folder/name for name in ('tls.key','aes.key','templates.db','gateway.py','face.py','gateway.json')]
        for path in denied:
            path.write_bytes(b'harmless synthetic sentinel')
        server.bind(('127.0.0.1',0))
        server.listen(1)
        with socket.create_connection(server.getsockname(),timeout=5) as client,server.accept()[0] as peer:
            read_up,write_up=os.pipe()
            read_down,write_down=os.pipe()
            with os.fdopen(read_up,'rb') as upstream,os.fdopen(write_up,'wb') as to_gateway,                  os.fdopen(read_down,'rb') as from_gateway,os.fdopen(write_down,'wb') as downstream:
                process=launch(peer,to_gateway,from_gateway,denied)
                to_gateway.close()
                from_gateway.close()
                try:
                    client.sendall(b'tls-like-opaque-bytes')
                    assert upstream.read(len(b'tls-like-opaque-bytes'))==b'tls-like-opaque-bytes'
                    downstream.write(b'opaque-reply')
                    downstream.flush()
                    assert client.recv(64)==b'opaque-reply'
                    client.shutdown(socket.SHUT_WR)
                    downstream.close()
                    assert process.wait(timeout=8)==0
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
    print('Relay AppContainer, accepted socket, anonymous pipes and deny controls: OK')


if __name__=='__main__':
    main()
