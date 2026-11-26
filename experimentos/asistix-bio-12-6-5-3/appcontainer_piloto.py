"""Synthetic-only AppContainer launcher with no network capability SIDs."""
import _winapi
from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import subprocess
import sys

from token_restringido import (
    ExtendedStartup, ProcessInfo, api, check, close, current, delete, info,
    initialize, kernel, local_free, open_token, pointer, update, auth,
)

PROFILE = 'ASISTIX.Face.Verification.12653'
ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / 'runtime/pilot-python'
STAGE = RUNTIME / 'sandbox'
EXECUTABLE = RUNTIME / 'asistix-face.exe'
userenv = c.WinDLL('userenv', use_last_error=True)
make_profile = api(userenv,'CreateAppContainerProfile',c.c_long,w.LPCWSTR,w.LPCWSTR,w.LPCWSTR,pointer,w.DWORD,c.POINTER(pointer))
derive = api(userenv,'DeriveAppContainerSidFromAppContainerName',c.c_long,w.LPCWSTR,c.POINTER(pointer))
sid_to_string = api(auth,'ConvertSidToStringSidW',w.BOOL,pointer,c.POINTER(pointer))
free_sid = api(auth,'FreeSid',pointer,pointer)
create = api(kernel,'CreateProcessW',w.BOOL,w.LPCWSTR,w.LPWSTR,pointer,pointer,w.BOOL,w.DWORD,
             pointer,w.LPCWSTR,pointer,c.POINTER(ProcessInfo))


class Capabilities(c.Structure):
    _fields_ = [('sid',pointer),('capabilities',pointer),('count',w.DWORD),('reserved',w.DWORD)]


@contextmanager
def profile_sid(provision=False, profile=PROFILE):
    sid = pointer()
    if provision:
        code = make_profile(profile,'ASISTIX facial pilot','Synthetic facial worker',None,0,c.byref(sid))
        if code & 0xffffffff == 0x800700B7:
            code = derive(profile,c.byref(sid))
    else:
        code = derive(profile,c.byref(sid))
    if code:
        raise RuntimeError(f'AppContainer SID/profile HRESULT 0x{code & 0xffffffff:08X}')
    try:
        yield sid
    finally:
        free_sid(sid)


def provision(executable=EXECUTABLE, stage=STAGE, profile=PROFILE, writable=None, readonly=None):
    with profile_sid(provision=True, profile=profile) as sid:
        string = pointer()
        check(sid_to_string(sid,c.byref(string)))
        try:
            principal = '*'+c.wstring_at(string)
        finally:
            local_free(string)
    runtime = executable.parent
    executable_files = [executable, *runtime.glob('*.dll'), runtime/'python313._pth']
    acl = str(Path(os.environ['SystemRoot'])/'System32/icacls.exe')
    for path in executable_files:
        subprocess.run([acl,str(path),'/grant:r',principal+':(RX)'],check=True,capture_output=True)
    subprocess.run([acl,str(stage),'/grant:r',principal+':(OI)(CI)(RX)'],check=True,capture_output=True)
    if readonly:
        subprocess.run([acl,str(readonly),'/grant:r',principal+':(OI)(CI)(RX)'],check=True,capture_output=True)
    if writable:
        subprocess.run([acl,str(writable),'/grant:r',principal+':(OI)(CI)(M)'],check=True,capture_output=True)


@contextmanager
def appcontainer_creation(executable=EXECUTABLE, stage=STAGE, profile=PROFILE, extra_handles=()):
    original = _winapi.CreateProcess
    with profile_sid(profile=profile) as sid:
        caps = Capabilities(sid,None,0,0)
        child_policy = w.DWORD(1)
        def launch(application, command, pa, ta, inherit, flags, env, directory, startup):
            if Path(application or executable).resolve() != executable or pa or ta or not inherit or env is not None:
                raise RuntimeError('Unexpected AppContainer startup configuration')
            handles = tuple(startup.lpAttributeList.get('handle_list',()))
            if set(handles) != {startup.hStdInput,startup.hStdOutput,startup.hStdError,*extra_handles}:
                raise RuntimeError('Unexpected inherited IPC descriptor')
            size = c.c_size_t()
            initialize(None,3,0,c.byref(size))
            attrs = c.create_string_buffer(size.value)
            check(initialize(attrs,3,0,c.byref(size)))
            try:
                values = (w.HANDLE*len(handles))(*handles)
                check(update(attrs,0,0x20002,values,c.sizeof(values),None,None))
                check(update(attrs,0,0x20009,c.byref(caps),c.sizeof(caps),None,None))
                check(update(attrs,0,0x2000E,c.byref(child_policy),c.sizeof(child_policy),None,None))
                config = ExtendedStartup()
                config.attributes = c.addressof(attrs)
                config.startup.size = c.sizeof(config)
                config.startup.flags = startup.dwFlags
                config.startup.stdin,config.startup.stdout,config.startup.stderr = startup.hStdInput,startup.hStdOutput,startup.hStdError
                allowed = ('APPDATA','LOCALAPPDATA','PROGRAMDATA','SYSTEMDRIVE',
                           'SYSTEMROOT','TEMP','TMP','USERPROFILE','WINDIR')
                block = [f'{name}={os.environ[name]}' for name in allowed if name in os.environ]
                block.append('PATH='+str(Path(os.environ['SystemRoot'])/'System32'))
                environment = c.create_unicode_buffer('\0'.join(sorted(block,key=str.casefold))+'\0\0')
                result = ProcessInfo()
                check(create(str(executable),c.create_unicode_buffer(command),None,None,True,
                             flags|0x80000|0x8|0x400,environment,str(stage),c.byref(config),c.byref(result)))
                return result.process,result.thread,result.pid,result.tid
            finally:
                delete(attrs)
        _winapi.CreateProcess = launch
        try:
            yield
        finally:
            _winapi.CreateProcess = original


if __name__=='__main__' and sys.argv[1:]==['--provision']:
    provision()
