"""Read-only rights probe for the executable that terminates test HTTPS."""
import ctypes
import json
from pathlib import Path
import sys
import tempfile

from comprobar_aislamiento import command_probe, connect
from probar_intermediarios import probe_scm, probe_wmi

ROOT = Path(__file__).resolve().parent
EXPECTED = ROOT/'runtime/pilot-gateway/asistix-gateway.exe'


def readable(path):
    try:
        with path.open('rb'):
            return True
    except PermissionError:
        return False


def main():
    if not Path(sys.executable).samefile(EXPECTED):
        raise RuntimeError('Only the dedicated gateway executable may run this probe')
    buffer=ctypes.create_unicode_buffer(32768)
    ctypes.windll.kernel32.GetModuleFileNameW(None,buffer,len(buffer))
    assert Path(buffer.value).samefile(EXPECTED)
    command_probe()  # Benign exit-only command, no network or data.
    with tempfile.TemporaryDirectory(dir=ROOT/'runtime') as directory:
        probe=Path(directory)/'sentinel.txt'
        probe.write_bytes(b'only a synthetic marker')
        own_write=probe.read_bytes()==b'only a synthetic marker'
    print(json.dumps({
        'process_image':EXPECTED.name,
        'direct_external_ipv4':connect('1.1.1.1'),
        'direct_external_ipv6':connect('2606:4700:4700::1111'),
        'direct_child_allowed':True,
        'wmi_connect_hresult':probe_wmi(),
        'scm_access_errors':probe_scm(),
        'outside_runtime_file_open_for_read':readable(ROOT.parents[1]/'backend/asistix.db'),
        'tls_key_open_for_read':readable(ROOT.parents[1]/'.certs/asistix-key.pem'),
        'own_runtime_file_write':own_write,
    }))


if __name__=='__main__':
    main()
