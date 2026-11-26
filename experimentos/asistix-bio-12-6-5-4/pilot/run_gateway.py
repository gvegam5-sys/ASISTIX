"""Closed by default. Wi-Fi arming additionally requires the scoped active Windows rules."""
import argparse
from ipaddress import ip_network
from pathlib import Path
import subprocess
import sys
import time

from cryptography import x509
from ipaddress import ip_address

from prepare_closed import HOST, PRIVATE
from supervisor_qr import EXECUTABLE, ROOT, Supervisor


PORT = 5192


def require_firewall():
    supervisor = ROOT/'runtime/pilot-supervisor/asistix-supervisor.exe'
    if not Path(sys.executable).samefile(supervisor):
        raise RuntimeError('Use the dedicated 12.6.5.4 supervisor')
    command = f"""$ErrorActionPreference='Stop'
$worker=Get-NetFirewallRule -PolicyStore ActiveStore -Name 'ASISTIX-Pilot-12653-Block-External'
$wifi=Get-NetFirewallRule -PolicyStore ActiveStore -Name 'ASISTIX-Pilot-12654-WiFi-HTTPS'
$app=$wifi|Get-NetFirewallApplicationFilter
$addr=$wifi|Get-NetFirewallAddressFilter
$port=$wifi|Get-NetFirewallPortFilter
$interface=$wifi|Get-NetFirewallInterfaceFilter
$ip=Get-NetIPAddress -InterfaceAlias 'Wi-Fi' -AddressFamily IPv4 -IPAddress '{HOST}'
if(@($worker).Count -ne 1 -or $worker.Enabled -ne 'True' -or $worker.Direction -ne 'Outbound' -or $worker.Action -ne 'Block' -or
 ($worker|Get-NetFirewallApplicationFilter).Program -ne '{EXECUTABLE}' -or
 ($worker|Get-NetFirewallAddressFilter).RemoteAddress -ne 'Any' -or $worker.Profile -ne 'Any' -or
 @($wifi).Count -ne 1 -or $wifi.Enabled -ne 'True' -or $wifi.Direction -ne 'Inbound' -or $wifi.Action -ne 'Allow' -or
 $wifi.Profile -ne 'Public' -or $wifi.EdgeTraversalPolicy -ne 'Block' -or $app.Program -ne '{supervisor}' -or
 $port.LocalPort -ne '{PORT}' -or $port.Protocol -notin @('TCP',6) -or
 @($addr.LocalAddress).Count -ne 1 -or @($addr.LocalAddress)[0] -ne '{HOST}' -or
 @($addr.RemoteAddress).Count -ne 1 -or @($addr.RemoteAddress)[0] -notin @('192.168.100.0/24','192.168.100.0/255.255.255.0') -or
 @($interface.InterfaceAlias).Count -ne 1 -or @($interface.InterfaceAlias)[0] -ne 'Wi-Fi' -or
 $ip.PrefixLength -ne 24 -or (Get-NetConnectionProfile -InterfaceIndex $ip.InterfaceIndex).NetworkCategory -ne 'Public'){{exit 3}}"""
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],
                   check=True,capture_output=True,timeout=15)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--arm-voluntary-capture',action='store_true')
    args=parser.parse_args()
    host=HOST if args.arm_voluntary_capture else '127.0.0.1'
    if args.arm_voluntary_capture:
        require_firewall()
    keys=PRIVATE/'keys'
    certificate=x509.load_pem_x509_certificate((keys/'tls.pem').read_bytes())
    names=certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    if ip_address(host) not in names.get_values_for_type(x509.IPAddress):
        raise RuntimeError('The approved address is absent from the certificate')
    with Supervisor(PRIVATE/'state',keys,host=host,port=PORT,
                    network=str(ip_network(host+('/24' if args.arm_voluntary_capture else '/32'),strict=False)),
                    physical_authorized=args.arm_voluntary_capture) as supervisor:
        print(supervisor.origin,flush=True)
        try:
            while supervisor.gateway.poll() is None:
                time.sleep(.25)
        except KeyboardInterrupt:
            pass


if __name__=='__main__':
    main()
