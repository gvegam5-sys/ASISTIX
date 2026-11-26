"""Minimal restricted-primary-token launcher for synthetic worker validation."""
import _winapi
from contextlib import ExitStack, contextmanager
import ctypes as c
from ctypes import wintypes as w

kernel = c.WinDLL('kernel32', use_last_error=True)
auth = c.WinDLL('advapi32', use_last_error=True)
pointer = c.c_void_p


def api(dll, name, result, *args):
    fn = getattr(dll,name)
    fn.argtypes,fn.restype = args,result
    return fn


class SidAttributes(c.Structure):
    _fields_ = [('sid',pointer),('attributes',w.DWORD)]


class Startup(c.Structure):
    _fields_ = ([('size',w.DWORD)] + [(n,w.LPWSTR) for n in ('reserved','desktop','title')] +
                [(n,w.DWORD) for n in ('x','y','xs','ys','xc','yc','fill','flags')] +
                [('show',w.WORD),('reserved2size',w.WORD),('reserved2',pointer)] +
                [(n,w.HANDLE) for n in ('stdin','stdout','stderr')])


class ExtendedStartup(c.Structure):
    _fields_ = [('startup',Startup),('attributes',pointer)]


class ProcessInfo(c.Structure):
    _fields_ = [('process',w.HANDLE),('thread',w.HANDLE),('pid',w.DWORD),('tid',w.DWORD)]


close = api(kernel,'CloseHandle',w.BOOL,w.HANDLE)
local_free = api(kernel,'LocalFree',pointer,pointer)
current = api(kernel,'GetCurrentProcess',w.HANDLE)
open_token = api(auth,'OpenProcessToken',w.BOOL,w.HANDLE,w.DWORD,c.POINTER(w.HANDLE))
restrict = api(auth,'CreateRestrictedToken',w.BOOL,w.HANDLE,w.DWORD,w.DWORD,pointer,w.DWORD,pointer,w.DWORD,pointer,c.POINTER(w.HANDLE))
convert = api(auth,'ConvertStringSidToSidW',w.BOOL,w.LPCWSTR,c.POINTER(pointer))
sid_length = api(auth,'GetLengthSid',w.DWORD,pointer)
set_token = api(auth,'SetTokenInformation',w.BOOL,w.HANDLE,c.c_int,pointer,w.DWORD)
info = api(auth,'GetTokenInformation',w.BOOL,w.HANDLE,c.c_int,pointer,w.DWORD,c.POINTER(w.DWORD))
initialize = api(kernel,'InitializeProcThreadAttributeList',w.BOOL,pointer,w.DWORD,w.DWORD,c.POINTER(c.c_size_t))
update = api(kernel,'UpdateProcThreadAttribute',w.BOOL,pointer,w.DWORD,c.c_size_t,pointer,c.c_size_t,pointer,pointer)
delete = api(kernel,'DeleteProcThreadAttributeList',None,pointer)
create = api(auth,'CreateProcessAsUserW',w.BOOL,w.HANDLE,w.LPCWSTR,w.LPWSTR,pointer,pointer,w.BOOL,w.DWORD,
             pointer,w.LPCWSTR,pointer,c.POINTER(ProcessInfo))


def check(result):
    if not result:
        raise c.WinError(c.get_last_error())


def restrictions():
    with ExitStack() as stack:
        token = w.HANDLE()
        check(open_token(current(),0x8,c.byref(token)))
        stack.callback(close,token)
        value,size = w.DWORD(),w.DWORD()
        check(info(token,21,c.byref(value),c.sizeof(value),c.byref(size)))  # TokenHasRestrictions
        return bool(value.value)


@contextmanager
def restricted_process_creation():
    original = _winapi.CreateProcess
    with ExitStack() as stack:
        primary, limited = w.HANDLE(),w.HANDLE()
        check(open_token(current(),0x8b,c.byref(primary)))  # assign, duplicate, query, adjust default
        stack.callback(close,primary)
        check(restrict(primary,1,0,None,0,None,0,None,c.byref(limited)))  # DISABLE_MAX_PRIVILEGE
        stack.callback(close,limited)
        sid = pointer()
        check(convert('S-1-16-4096',c.byref(sid)))
        stack.callback(local_free,sid)
        label = SidAttributes(sid,0x20)
        check(set_token(limited,25,c.byref(label),c.sizeof(label)+sid_length(sid)))

        def launch(application, command, pa, ta, inherit, flags, env, directory, startup):
            if pa or ta or not inherit or env is not None:
                raise RuntimeError('Unexpected synthetic worker startup configuration')
            handles = tuple(startup.lpAttributeList.get('handle_list',()))
            if not handles or not set(handles) == {startup.hStdInput,startup.hStdOutput,startup.hStdError}:
                raise RuntimeError('Only the three IPC descriptors may be inherited')
            count = c.c_size_t()
            initialize(None,1,0,c.byref(count))
            if not count.value:
                raise c.WinError(c.get_last_error())
            attrs = c.create_string_buffer(count.value)
            check(initialize(attrs,1,0,c.byref(count)))
            try:
                values = (w.HANDLE * len(handles))(*handles)
                check(update(attrs,0,0x20002,values,c.sizeof(values),None,None))
                details = ExtendedStartup()
                details.attributes = c.addressof(attrs)
                details.startup.size = c.sizeof(details)
                details.startup.flags = startup.dwFlags
                details.startup.show = startup.wShowWindow
                details.startup.stdin,details.startup.stdout,details.startup.stderr = startup.hStdInput,startup.hStdOutput,startup.hStdError
                result = ProcessInfo()
                check(create(limited,application,c.create_unicode_buffer(command),None,None,True,
                             flags|0x80000|0x08000000,None,directory,c.byref(details),c.byref(result)))
                return result.process,result.thread,result.pid,result.tid
            finally:
                delete(attrs)

        _winapi.CreateProcess = launch
        try:
            yield
        finally:
            _winapi.CreateProcess = original
