"""Read-only broker probe from the worker's actual Windows token."""
import ctypes as c
from ctypes import wintypes as w
import uuid

ole = c.OleDLL('ole32')
auto = c.WinDLL('oleaut32')
auto.SysAllocString.argtypes = [w.LPCWSTR]
auto.SysAllocString.restype = c.c_void_p
auto.SysFreeString.argtypes = [c.c_void_p]


def guid(value):
    return (c.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le)


def method(interface, index, result, *args):
    table = c.cast(interface, c.POINTER(c.POINTER(c.c_void_p))).contents
    return c.WINFUNCTYPE(result, c.c_void_p, *args)(table[index])


def probe_wmi():
    ole.CoInitializeEx(None, 0)
    locator, services = c.c_void_p(), c.c_void_p()
    namespace = auto.SysAllocString(r'ROOT\CIMV2')
    if not namespace:
        raise MemoryError('BSTR allocation failed')
    try:
        ole.CoCreateInstance(c.byref(guid('4590F811-1D3A-11D0-891F-00AA004B2E24')), None, 1,
                             c.byref(guid('DC12A687-737F-11CF-884D-00AA004B2E24')), c.byref(locator))
        connect = method(locator, 3, c.c_long, *([c.c_void_p]*4), c.c_long, c.c_void_p,
                         c.c_void_p, c.POINTER(c.c_void_p))
        result = connect(locator, namespace, None, None, None, 0x80, None, None, c.byref(services))
        return f'0x{result & 0xffffffff:08X}'
    except OSError as error:
        if error.winerror is None:
            raise
        return f'0x{error.winerror & 0xffffffff:08X}'
    finally:
        for interface in (services,locator):
            if interface:
                method(interface,2,w.ULONG)(interface)
        auto.SysFreeString(namespace)
        ole.CoUninitialize()

def probe_scm():
    """Test access masks only. No service is opened or changed."""
    advapi = c.WinDLL('advapi32', use_last_error=True)
    advapi.OpenSCManagerW.argtypes = [w.LPCWSTR,w.LPCWSTR,w.DWORD]
    advapi.OpenSCManagerW.restype = w.HANDLE
    advapi.CloseServiceHandle.argtypes = [w.HANDLE]
    advapi.CloseServiceHandle.restype = w.BOOL
    results = {}
    for name, access in (('connect',1),('create_service',3),('lock_database',9),('modify_boot',33)):
        handle = advapi.OpenSCManagerW(None,None,access)
        results[name] = 0 if handle else c.get_last_error()
        if handle:
            advapi.CloseServiceHandle(handle)
    return results
