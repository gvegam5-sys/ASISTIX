"""Synthetic-only probe for the future firewall + IPC boundary."""
import ctypes
from contextlib import nullcontext
from ctypes import wintypes
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
WORKER = ROOT.parent / 'asistix-face.exe' if ROOT.name == 'sandbox' else ROOT / 'runtime/pilot-python/asistix-face.exe'
MAX_FRAME = 256
kernel = ctypes.WinDLL('kernel32', use_last_error=True)


class BasicLimits(ctypes.Structure):
    _fields_ = [
        ('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
        ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
        ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
        ('SchedulingClass', wintypes.DWORD),
    ]


kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
kernel.CreateJobObjectW.restype = wintypes.HANDLE
kernel.GetCurrentProcess.argtypes = []
kernel.GetCurrentProcess.restype = wintypes.HANDLE
kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
kernel.SetInformationJobObject.restype = wintypes.BOOL
kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel.AssignProcessToJobObject.restype = wintypes.BOOL


def enter_job():
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = BasicLimits()
    limits.LimitFlags = 0x8  # JOB_OBJECT_LIMIT_ACTIVE_PROCESS; no breakaway.
    limits.ActiveProcessLimit = 1
    if not kernel.SetInformationJobObject(job, 2, ctypes.byref(limits), ctypes.sizeof(limits)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())
    return job  # Keep the noninheritable handle open until the worker exits.


def command_probe():
    return subprocess.run(
        [str(Path(os.environ['SystemRoot'])/'System32/cmd.exe'), '/d', '/c', 'exit', '0'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True, timeout=3, check=True,
    )


def endpoint(ip):
    address = ipaddress.ip_address(ip)
    if not address.is_global:
        raise ValueError('Use a public numeric address for the egress control.')
    return address


def connect(ip):
    address = endpoint(ip)
    family = socket.AF_INET if address.version == 4 else socket.AF_INET6
    try:
        with socket.socket(family, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect((str(address), 443))
        return True
    except OSError:
        return False


def is_appcontainer():
    from token_restringido import check, close, current, info, open_token
    token, flag, size = wintypes.HANDLE(), wintypes.DWORD(), wintypes.DWORD()
    check(open_token(current(),0x8,ctypes.byref(token)))
    try:
        check(info(token,29,ctypes.byref(flag),ctypes.sizeof(flag),ctypes.byref(size)))
        return bool(flag.value)
    finally:
        close(token)


def worker():
    if not Path(sys.executable).samefile(WORKER):
        raise RuntimeError('Wrong worker executable')
    from token_restringido import restrictions
    restricted = restrictions()
    appcontainer = is_appcontainer()
    if appcontainer:
        try:
            with (ROOT.parent / 'fuera-del-trabajador.txt').open('rb'):
                outside_denied = False
        except PermissionError:
            outside_denied = True
    else:
        outside_denied = None
    job = enter_job()
    raw = sys.stdin.buffer.readline(MAX_FRAME + 1)
    if len(raw) > MAX_FRAME or not raw.endswith(b'\n'):
        raise ValueError('Invalid IPC frame')
    ip = json.loads(raw)['ip']
    try:
        command_probe()
    except OSError as error:
        if error.winerror not in ((5, 367, 1816) if appcontainer else (5, 1816)):
            raise
    else:
        raise RuntimeError('Unexpected child process allowed')
    sent = connect(ip) if ip else None
    from probar_intermediarios import probe_scm, probe_wmi
    wmi = probe_wmi()
    scm = probe_scm()
    import cv2
    from motor import FacialEngine

    fixture = cv2.imread(str(ROOT / 'engine/portrait-a.png'))
    resized = cv2.resize(fixture,(640,640))
    jpeg = cv2.imencode('.jpg',resized)[1].tobytes()
    valid = len(FacialEngine().capture(jpeg)) == 512
    assert job and valid
    print(json.dumps({'ipc':True,'child_blocked':True,'inference':True,'external_connected':sent,'wmi_connect_hresult':wmi,'scm_access_errors':scm,'restricted':restricted,'appcontainer':appcontainer,'outside_read_denied':outside_denied}),flush=True)


def controller(address=None, *, limited=False, app=False):
    command_probe()  # Positive control for process creation without the Job.
    if address and not connect(address):
        raise RuntimeError('External positive control failed; egress proof is inconclusive.')
    frame = json.dumps({'ip':address}) + '\n'
    from token_restringido import restricted_process_creation
    from appcontainer_piloto import STAGE, appcontainer_creation
    mode = appcontainer_creation() if app else restricted_process_creation() if limited else nullcontext()
    entry = STAGE / Path(__file__).name if app else Path(__file__).resolve()
    with mode:
        result = subprocess.run(
            [str(WORKER),'-B','-I',str(entry),'--worker'],
            input=frame,text=True,capture_output=True,timeout=25,check=False,close_fds=True,
        )
    if result.returncode:
        raise RuntimeError(f'Worker exit 0x{result.returncode & 0xffffffff:08X}: {result.stderr[-3500:]}')
    report = json.loads(result.stdout)
    if app and (not report['appcontainer'] or not report['outside_read_denied']):
        raise RuntimeError('AppContainer identity or file restriction could not be attested')
    if limited and not report['restricted']:
        raise RuntimeError('The worker did not attest its restricted token')
    if address and report['external_connected'] is not False:
        raise RuntimeError('The worker established an external connection; keep capture disabled.')
    print(json.dumps(report))


if __name__ == '__main__':
    if sys.argv[1:] == ['--worker']:
        worker()
    elif sys.argv[1:] == ['--appcontainer']:
        controller(app=True)
    elif len(sys.argv) == 3 and sys.argv[1] == '--appcontainer-egress':
        controller(sys.argv[2], app=True)
    elif sys.argv[1:] == ['--restricted']:
        controller(limited=True)
    elif len(sys.argv) == 3 and sys.argv[1] == '--restricted-egress':
        controller(sys.argv[2], limited=True)
    elif sys.argv[1:] == ['--local']:
        controller()
    elif len(sys.argv) == 3 and sys.argv[1] == '--egress':
        controller(sys.argv[2])
    else:
        raise SystemExit('Use --local or --egress PUBLIC_NUMERIC_IP')
