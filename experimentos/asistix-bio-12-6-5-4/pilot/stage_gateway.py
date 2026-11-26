"""Stage local executables and code for the closed QR pilot. No data or keys copied."""
from importlib.metadata import distribution
from pathlib import Path
from shutil import copy2, copytree, ignore_patterns


root = Path(__file__).resolve().parents[1]
source = root.parent / 'asistix-bio-12-6-5-3'
target = root / 'runtime/pilot-gateway'
web = root / 'frontend/demo-dist-nuevo'


if __name__ == '__main__':
    if not (web / 'index.html').is_file():
        raise SystemExit('Build the experimental frontend first')
    copytree(source/'runtime/pilot-gateway', target, dirs_exist_ok=True,
             ignore=ignore_patterns('web','test-portrait.png','__pycache__','gateway_persistente.py','registro.py'))
    stage = target/'sandbox'
    for name in ('SQLAlchemy','greenlet','pydantic-settings','python-dotenv','email-validator','dnspython',
                 'PyJWT','pwdlib','argon2-cffi','argon2-cffi-bindings','tzdata','reportlab','XlsxWriter','pillow'):
        package = distribution(name)
        for relative in package.files or ():
            if '..' in relative.parts or '__pycache__' in relative.parts:
                continue
            original = package.locate_file(relative)
            if original.is_file():
                destination = stage/'site-packages'/relative
                destination.parent.mkdir(parents=True,exist_ok=True)
                copy2(original,destination)
    copytree(root/'backend/app',stage/'app',dirs_exist_ok=True,ignore=ignore_patterns('__pycache__'))
    copytree(web,stage/'web',dirs_exist_ok=True)
    copy2(root/'pilot/gateway_academico.py',stage/'gateway_academico.py')
    transport = (source/'gateway_tls_piloto.py').read_text(encoding='utf-8')
    core = transport[transport.index('MAX_CAPTURE = '):transport.index('\ndef main():')]
    (stage/'gateway_transport.py').write_text('import asyncio\nimport os\nimport ssl\n\nimport h11\n\n'+core,
                                              encoding='utf-8')
    supervisor = root/'runtime/pilot-supervisor'
    copytree(source/'runtime/pilot-supervisor',supervisor,dirs_exist_ok=True)
    pth = supervisor/'python313._pth'
    paths = pth.read_text(encoding='utf-8-sig').splitlines()
    pth.write_text('\n'.join([str(root/'pilot'), *paths[1:]])+'\n',encoding='utf-8')
    print('Runtime aislado preparado. La captura física continúa desactivada.')
