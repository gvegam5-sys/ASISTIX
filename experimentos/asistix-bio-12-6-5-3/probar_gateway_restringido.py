"""Read-only synthetic isolation probe using the gateway AppContainer."""
import json
from pathlib import Path
import subprocess
import sys

from comprobar_aislamiento import command_probe,connect,enter_job,is_appcontainer
from probar_intermediarios import probe_scm,probe_wmi


def worker(address):
    assert is_appcontainer()
    job=enter_job()
    try:
        command_probe()
    except OSError as error:
        assert error.winerror in (5,367,1816)
    else:
        raise RuntimeError('Gateway created a secondary process')
    assert job
    try:
        with (Path(__file__).resolve().parents[1]/'centinela-fuera.txt').open('rb'):
            raise RuntimeError('Gateway can read the file outside its stage')
    except PermissionError:
        pass
    print(json.dumps({'appcontainer':True,'child_blocked':True,'external_connected':connect(address),
                      'outside_read_denied':True,'wmi_hresult':probe_wmi(),'scm':probe_scm()}))


def control():
    from appcontainer_piloto import appcontainer_creation,provision
    from test_rele_tls_piloto import GATEWAY,GATEWAY_STAGE,PROFILE
    provision(GATEWAY,GATEWAY_STAGE,PROFILE)
    for address in ('1.1.1.1','2606:4700:4700::1111'):
        assert connect(address),'External control failed'
        with appcontainer_creation(GATEWAY,GATEWAY_STAGE,PROFILE):
            result=subprocess.run([str(GATEWAY),'-B','-I',str(GATEWAY_STAGE/Path(__file__).name),address],
                                  input=b'',capture_output=True,close_fds=True,timeout=12)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors='replace')[-3000:])
        data=json.loads(result.stdout)
        assert data['external_connected'] is False and data['wmi_hresult']=='0x80070005'
        assert all(data['scm'][name]==5 for name in ('create_service','lock_database','modify_boot'))
        print(address,json.dumps(data))


if __name__=='__main__':
    worker(sys.argv[1]) if len(sys.argv)==2 else control()
