"""Single-connection proof of TLS termination inside the gateway AppContainer."""
import asyncio
import ipaddress
import os
from pathlib import Path
import ssl
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import h11
from fastapi.responses import FileResponse

from comprobar_aislamiento import enter_job, is_appcontainer
from registro import Store, create_app

MAX_CAPTURE = 384 * 1024


def channel(fd, mode):
    import msvcrt
    return os.fdopen(msvcrt.open_osfhandle(int(fd), os.O_BINARY),mode)


class PipeTLS:
    def __init__(self,context,input_stream,output_stream):
        self.input_stream,self.output_stream=input_stream,output_stream
        self.incoming,self.outgoing=ssl.MemoryBIO(),ssl.MemoryBIO()
        self.protocol=context.wrap_bio(self.incoming,self.outgoing,server_side=True)

    def pump(self, operation):
        while True:
            try:
                value=operation()
                self.flush()
                return value
            except ssl.SSLWantReadError:
                self.flush()
                chunk=self.input_stream.read1(65536)
                if not chunk:
                    raise EOFError('TLS stream ended')
                self.incoming.write(chunk)

    def flush(self):
        while self.outgoing.pending:
            self.output_stream.write(self.outgoing.read())
        self.output_stream.flush()


async def exchange(app, connection, request, body):
    incoming=False
    async def receive():
        nonlocal incoming
        if incoming:
            await asyncio.Future()
        incoming=True
        return {'type':'http.request','body':body,'more_body':False}

    status,headers,result=500,[],bytearray()
    async def send(message):
        nonlocal status,headers
        if message['type']=='http.response.start':
            status,headers=message['status'],message['headers']
        else:
            result.extend(message.get('body',b''))

    target,separator,query=request.target.partition(b'?')
    invalid=(not target.startswith(b'/') or target.startswith(b'//') or
             b'#' in request.target or any(byte<33 or byte>126 for byte in request.target) or
             (separator and request.method not in (b'GET',b'HEAD')))
    if invalid:
        status,headers,result=400,[(b'content-length',b'0'),(b'cache-control',b'no-store')],b''
    else:
        path=target.decode('ascii')
        await app({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':request.method.decode('ascii'),
                   'scheme':'https','path':path,'raw_path':target,'root_path':'','query_string':query,
                   'headers':list(request.headers),'client':('127.0.0.1',0),'server':('127.0.0.1',443)},receive,send)
    response=connection.send(h11.Response(status_code=status,headers=headers))
    if request.method!=b'HEAD' and result:
        response+=connection.send(h11.Data(data=result))
    return response+connection.send(h11.EndOfMessage())


def serve_lane(app, context, input_stream, output_stream):
    tls=PipeTLS(context,input_stream,output_stream)
    tls.pump(tls.protocol.do_handshake)
    http=h11.Connection(h11.SERVER,max_incomplete_event_size=16384)
    request,body=None,bytearray()
    while True:
        event=http.next_event()
        if event is h11.NEED_DATA:
            try:
                data=tls.pump(tls.protocol.read)
            except (EOFError,ssl.SSLZeroReturnError):
                break
            if not data:
                break
            http.receive_data(data)
        elif isinstance(event,h11.Request):
            request,body=event,bytearray()
        elif isinstance(event,h11.Data):
            if len(body)+len(event.data)>MAX_CAPTURE:
                raise ValueError('Request exceeds synthetic proof bound')
            body.extend(event.data)
        elif isinstance(event,h11.EndOfMessage):
            response=asyncio.run(exchange(app,http,request,bytes(body)))
            tls.pump(lambda: tls.protocol.write(response))
            if http.our_state is h11.MUST_CLOSE:
                break
            http.start_next_cycle()
        else:
            break

def main():
    if not is_appcontainer():
        raise RuntimeError('Gateway AppContainer required')
    job=enter_job()
    data,credentials,origin,writer,reader,*lanes=sys.argv[1:]
    folder,keys=Path(data),Path(credentials)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(keys/'tls.pem',keys/'tls.key')
    capture_lock=Lock()
    used=False
    def capture(jpeg):
        nonlocal used
        with capture_lock:
            if used:
                raise RuntimeError("This synthetic worker processes one capture")
            used=True
        # Complete the bounded frame before closing the face input.
        frame=len(jpeg).to_bytes(4,'big')+jpeg
        while frame:
            count=face_input.write(frame)
            if not count:
                raise RuntimeError('Face pipe closed')
            frame=frame[count:]
        face_input.flush()
        face_input.close()
        vector=face_output.read(513)
        if len(vector)!=512:
            raise RuntimeError('Unexpected worker reply')
        return vector

    with channel(writer,'wb') as face_input, channel(reader,'rb') as face_output:
        app=create_app(Store(folder/'isolated.db'),origin=origin,capture_enabled=True,
                       key=(keys/'aes.key').read_bytes(),capture=capture,client_network='127.0.0.1/32')
        fixture=Path(__file__).resolve().parent/'test-portrait.png'
        if fixture.is_file():
            @app.get('/synthetic-fixture')
            def synthetic_fixture():
                return FileResponse(fixture,media_type='image/png')

        if not job or len(lanes)%2 or len(lanes)>12:
            raise RuntimeError('Invalid synthetic lane configuration')
        if not lanes:
            serve_lane(app,context,sys.stdin.buffer,sys.stdout.buffer)
            return

        def lane(read_handle,write_handle):
            with channel(read_handle,'rb') as incoming,channel(write_handle,'wb') as outgoing:
                try:
                    serve_lane(app,context,incoming,outgoing)
                except (EOFError, ssl.SSLError, BrokenPipeError):
                    pass

        with ThreadPoolExecutor(max_workers=len(lanes)//2) as pool:
            futures=[pool.submit(lane,a,b) for a,b in zip(lanes[::2],lanes[1::2])]
            for future in futures:
                future.result()


if __name__=='__main__':
    main()
