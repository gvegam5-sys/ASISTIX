"""Academic HTTPS supervisor. Only descriptor metadata crosses control IPC."""
import _winapi
from contextlib import ExitStack
import itertools
from ipaddress import ip_address, ip_network
import select
import json
import msvcrt
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT.parent/'asistix-bio-12-6-5-3'
sys.path.insert(0,str(SOURCE))
from appcontainer_piloto import EXECUTABLE, STAGE, appcontainer_creation, provision
from test_identidad_rele import RELAY,STAGE as RELAY_STAGE,PROFILE as RELAY_PROFILE,launch
sys.path.pop(0)
GATEWAY=ROOT/'runtime/pilot-gateway/asistix-gateway.exe'
GATEWAY_STAGE=GATEWAY.parent/'sandbox'
PROFILE='ASISTIX.Gateway.QR.12654'

MAX_CONNECTIONS=12
MAX_WORKERS=4


def fd_scope(stack, mode, fd):
    return stack.enter_context(os.fdopen(fd,mode))


class Supervisor:
    def __init__(self,folder,keys,*,host='127.0.0.1',port=0,network='127.0.0.1/32',backend_port=None,physical_authorized=False):
        self.folder,self.keys=Path(folder),Path(keys)
        self.host,self.requested_port=host,port
        self.network=ip_network(network)
        self.backend_port=backend_port
        self.mode='voluntary-authorized' if physical_authorized else 'closed'
        self.listeners=[]
        self.stop=threading.Event()
        self.ready=threading.Event()
        self.lock=threading.RLock()
        self.launch_lock=threading.Lock()
        self.write_lock=threading.Lock()
        self.active={}
        self.workers={}
        self.errors=[]
        self.rejects=0
        self.high_workers=0
        self.finished_workers=0
        self.started_pids=set()
        self.sequence=itertools.count()
        self.listener=None
        self.gateway=None
        self.threads=[]

    def __enter__(self):
        try:
            return self.start()
        except BaseException:
            self.close()
            raise

    def __exit__(self,*args):
        self.close()

    def start(self):
        provision()
        provision(GATEWAY,GATEWAY_STAGE,PROFILE,writable=self.folder,readonly=self.keys)
        provision(RELAY,RELAY_STAGE,RELAY_PROFILE)
        self.listener=self.bind(self.host,self.requested_port)
        if self.backend_port is not None:
            self.bind('127.0.0.1',self.backend_port)
        self.port=self.listener.getsockname()[1]
        self.origin=f'https://{self.host}:{self.port}'
        with appcontainer_creation(GATEWAY,GATEWAY_STAGE,PROFILE):
            self.gateway=subprocess.Popen([str(GATEWAY),'-B','-I',str(GATEWAY_STAGE/'gateway_academico.py'),
                                          str(self.folder),str(self.keys),self.origin,self.mode],
                                         stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,close_fds=True)
        self.started_pids.add(self.gateway.pid)
        self.threads=[threading.Thread(target=fn,daemon=True) for fn in (self.dispatch,self.accept,self.reap)]
        for thread in self.threads:
            thread.start()
        wait = 20
        if not self.ready.wait(wait) or self.gateway.poll() is not None:
            if self.host=='127.0.0.1' and self.gateway.poll() is not None:
                detail=self.gateway.stderr.read(1800).decode('utf8',errors='replace')
                raise RuntimeError('Synthetic gateway failed to start: '+detail)
            raise RuntimeError('Gateway failed to start')
        return self

    def bind(self,host,port):
        listener=socket.socket()
        self.listeners.append(listener)
        listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        listener.bind((host,port))
        listener.listen(MAX_CONNECTIONS)
        listener.settimeout(.25)
        return listener

    def remote(self, stream):
        return _winapi.DuplicateHandle(_winapi.GetCurrentProcess(),msvcrt.get_osfhandle(stream.fileno()),
                                     int(self.gateway._handle),0,False,2)

    def send(self, payload):
        with self.write_lock:
            self.gateway.stdin.write(json.dumps(payload).encode()+b'\n')
            self.gateway.stdin.flush()

    def accept(self):
        while not self.stop.is_set():
            try:
                readable,_,_=select.select(self.listeners,[],[],.25)
                if not readable:
                    continue
                selected=readable[0]
                peer,address=selected.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with peer:
                accepted=ip_address(address[0])
                permit=accepted in self.network if selected is self.listener else accepted.is_loopback
                if not permit:
                    continue
                with self.lock:
                    if len(self.active)>=MAX_CONNECTIONS:
                        self.rejects+=1
                        continue
                try:
                    self.add_connection(peer)
                except Exception as error:
                    self.errors.append(type(error).__name__)

    def add_connection(self,peer):
        identifier=next(self.sequence)
        with ExitStack() as stack:
            read_client,write_client=os.pipe()
            read_server,write_server=os.pipe()
            from_relay=fd_scope(stack,'rb',read_client)
            to_gateway=fd_scope(stack,'wb',write_client)
            from_gateway=fd_scope(stack,'rb',read_server)
            to_relay=fd_scope(stack,'wb',write_server)
            denied=(self.keys/'tls.key',self.keys/'jwt.secret',self.keys/'biometric.key',
                    self.folder/'asistix-biometria.db',self.folder/'revocations.db',
                    GATEWAY_STAGE/'gateway_academico.py', GATEWAY_STAGE/'app/biometric_attendance.py',
                    STAGE/'worker_sintetico_ipc.py',GATEWAY.parent/'python313._pth')
            with self.launch_lock:
                process=launch(peer,to_gateway,from_gateway,denied,check_egress=self.host=='127.0.0.1')
            with self.lock:
                if self.stop.is_set():
                    process.kill()
                    process.wait(timeout=5)
                    process.stdout.close()
                    process.stderr.close()
                    return
                self.active[identifier]=process
                self.started_pids.add(process.pid)
            handles=[self.remote(from_relay),self.remote(to_relay)]
            self.send({'op':'lane','id':identifier,'handles':handles})

    def dispatch(self):
        while not self.stop.is_set():
            line=self.gateway.stdout.readline(1025)
            if not line:
                return
            message=json.loads(line)
            if message['op']=='ready':
                self.ready.set()
            elif message['op']=='face':
                try:
                    self.add_worker(message['id'])
                except Exception as error:
                    self.errors.append(type(error).__name__)
                    self.send({'op':'face','id':message['id']})

    def add_worker(self, identifier):
        deadline=time.monotonic()+1
        while not self.stop.is_set():
            with self.lock:
                for pid,(proc,_) in tuple(self.workers.items()):
                    if proc.poll() is not None:
                        self.finish_worker(pid,proc)
                if len(self.workers)<MAX_WORKERS:
                    break
            if time.monotonic()>=deadline:
                self.send({'op':'face','id':identifier})
                return
            self.stop.wait(.04)
        if self.stop.is_set():
            return
        with ExitStack() as stack:
            read_jpeg,write_jpeg=os.pipe()
            read_result,write_result=os.pipe()
            source=fd_scope(stack,'rb',read_jpeg)
            destination=fd_scope(stack,'wb',write_result)
            to_worker=fd_scope(stack,'wb',write_jpeg)
            from_worker=fd_scope(stack,'rb',read_result)
            with self.launch_lock,appcontainer_creation():
                worker=subprocess.Popen([str(EXECUTABLE),'-B','-I',str(STAGE/'worker_sintetico_ipc.py'),'--quality-feedback'],
                                         stdin=source,stdout=destination,stderr=subprocess.PIPE,close_fds=True)
            with self.lock:
                if self.stop.is_set():
                    worker.kill()
                    worker.wait(timeout=5)
                    worker.stderr.close()
                    return
                self.workers[worker.pid]=(worker,time.monotonic())
                self.started_pids.add(worker.pid)
                self.high_workers=max(self.high_workers,len(self.workers))
            self.send({'op':'face','id':identifier,'handles':[self.remote(from_worker),self.remote(to_worker)]})

    def finish_worker(self,pid,process):
        self.workers.pop(pid)
        self.finished_workers+=1
        process.stderr.close()

    def reap(self):
        while not self.stop.wait(.1):
            with self.lock:
                for identifier,process in tuple(self.active.items()):
                    if process.poll() is not None:
                        self.active.pop(identifier)
                        process.stdout.close()
                        process.stderr.close()
                for pid,(process,start) in tuple(self.workers.items()):
                    if process.poll() is not None:
                        self.finish_worker(pid,process)
                    elif time.monotonic()-start>9:
                        process.kill()

    def close(self):
        if self.stop.is_set():
            return
        self.stop.set()
        for listener in self.listeners:
            listener.close()
        # Stop acceptance before enumerating processes that must be reaped.
        for thread in self.threads[1:]:
            thread.join(timeout=6)
        with self.lock:
            children=list(self.active.values())+[item[0] for item in self.workers.values()]
        for process in children:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=6)
            for stream in (process.stdin,process.stdout,process.stderr):
                if stream:
                    stream.close()
        if self.gateway:
            if self.gateway.poll() is None:
                try:
                    self.send({'op':'stop'})
                    self.gateway.wait(timeout=6)
                except (OSError,subprocess.TimeoutExpired):
                    self.gateway.kill()
                    self.gateway.wait(timeout=6)
            diagnostic=self.gateway.stderr.read()
            if diagnostic and self.gateway.returncode:
                self.errors.append('Gateway failed')
            for stream in (self.gateway.stdin,self.gateway.stdout,self.gateway.stderr):
                stream.close()
        for thread in self.threads:
            thread.join(timeout=3)
