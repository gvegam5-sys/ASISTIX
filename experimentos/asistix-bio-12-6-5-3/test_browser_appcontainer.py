"""Browser-side synthetic camera for the ephemeral HTTPS integration test."""
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
from time import monotonic, sleep
from urllib.request import urlopen
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed

CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'


def verify_browser(origin, password, runtime, test_spki=None):
    with tempfile.TemporaryDirectory(dir=runtime,ignore_cleanup_errors=True) as folder:
        profile = Path(folder)/'profile'
        chrome = subprocess.Popen([CHROME,'--headless=new','--no-first-run','--disable-background-networking','--autoplay-policy=no-user-gesture-required',
                                   '--remote-debugging-port=0','--user-data-dir='+str(profile),
                                   *(['--ignore-certificate-errors-spki-list='+test_spki] if test_spki else []),'about:blank'],
                                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    port = (profile/'DevToolsActivePort').read_text().splitlines()[0]
                    targets = json.load(urlopen(f'http://127.0.0.1:{port}/json/list',timeout=2))
                    target = next(item['webSocketDebuggerUrl'] for item in targets if item['type']=='page')
                    break
                except (OSError,StopIteration,IndexError):
                    sleep(.15)
            else:
                raise RuntimeError('Chrome did not open')
            with connect(target) as websocket:
                requests=[]
                def call(method,**params):
                    identifier=secrets.randbelow(1000000000)
                    websocket.send(json.dumps({'id':identifier,'method':method,'params':params}))
                    while True:
                        value=json.loads(websocket.recv(timeout=25))
                        if value.get('method')=='Network.requestWillBeSent':
                            request=value['params']['request']
                            requests.append((request['method'],request['url']))
                        if value.get('id')==identifier:
                            if 'error' in value:
                                raise RuntimeError('DevTools command failed')
                            return value.get('result',{})
                def evaluate(expression):
                    result=call('Runtime.evaluate',expression=expression,awaitPromise=True,returnByValue=True,userGesture=True)
                    if 'exceptionDetails' in result:
                        raise RuntimeError('JavaScript in isolated test browser failed')
                    return result.get('result',{}).get('value')
                def wait(expression):
                    deadline=monotonic()+15
                    while monotonic()<deadline:
                        if evaluate(expression):
                            return
                        sleep(.15)
                    raise RuntimeError('Expected browser state not reached: '+expression+' | '+str(evaluate("document.querySelector('#feedback')?.textContent || ''")))
                call('Page.enable')
                call('Network.enable')
                call('Page.addScriptToEvaluateOnNewDocument',source="""(() => {
                    if (!navigator.mediaDevices) return;
                    window.asistixSyntheticMedia=true;
                    Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:async () => {
                        if (location.hostname !== '127.0.0.1') throw new Error('Only test loopback');
                        const response=await fetch('/synthetic-fixture');
                        const image=await createImageBitmap(await response.blob());
                        const canvas=document.createElement('canvas');
                        canvas.width=640; canvas.height=640;
                        const stream=canvas.captureStream(10);
                        const context=canvas.getContext('2d');
                        const draw=()=>context.drawImage(image,0,0,640,640);
                        draw();
                        const timer=setInterval(() => {
                            if(stream.getTracks().every(track=>track.readyState==='ended')){
                                clearInterval(timer); image.close(); return;
                            }
                            draw();
                        },100);
                        window.testTracks=stream.getTracks();
                        return stream;
                    }});
                })();""")
                call('Page.navigate',url=origin)
                wait("document.readyState==='complete' && !!document.querySelector('#login input[name=login]')")
                evaluate("""(password => {
                    const form=document.querySelector('#login');
                    form.elements.login.value='synthetic-only';
                    form.elements.password.value=password;
                    form.requestSubmit();
                })("""+json.dumps(password)+")")
                wait("document.querySelector('#enrollment')?.hidden === false")
                assert evaluate("!document.querySelector('#consent').checked && document.querySelector('#open').disabled")
                assert evaluate("window.asistixSyntheticMedia === true")
                evaluate("document.querySelector('#consent').click();document.querySelector('#open').click()")
                wait("document.querySelector('#capture')?.disabled === false")
                evaluate("document.querySelector('#capture').click()")
                wait("document.querySelector('#feedback')?.dataset.tone === 'success'")
                assert evaluate("window.testTracks.every(t=>t.readyState==='ended') && document.querySelector('#preview').hidden")
                if evaluate("document.querySelector('#verification-panel')?.hidden === false"):
                    evaluate("document.querySelector('#verify-open').click()")
                    wait("document.querySelector('#capture')?.disabled === false")
                    evaluate("document.querySelector('#capture').click()")
                    wait("document.querySelector('#feedback')?.textContent.startsWith('Verificaci\u00f3n facial completada')")
                    assert evaluate("window.testTracks.every(t=>t.readyState==='ended')")
                    assert ('POST',origin+'/verification') in requests

                evaluate("window.confirm=()=>true;document.querySelector('#enrollment details').open=true;document.querySelector('#remove').click()")
                wait("document.querySelector('#registration')?.textContent.includes('no tienes')")
                assert ('POST',origin+'/enrollment') in requests and ('DELETE',origin+'/enrollment') in requests
                external=[url for _,url in requests if url.startswith(('http://','https://')) and not url.startswith(origin+'/')]
                assert not external,'The page made an external HTTP request'
                call('Page.navigate',url='about:blank')
                try:
                    call('Browser.close')
                except ConnectionClosed:
                    pass
        finally:
            if chrome.poll() is None:
                try:
                    chrome.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    chrome.terminate()
            chrome.wait(timeout=10)
