#Requires -Version 5.1
param([Parameter(Mandatory)][ValidateSet('Apply','Remove','Status')][string]$Action)
$ErrorActionPreference='Stop'
$principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if($Action -ne 'Status' -and -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
    throw 'Run Apply or Remove from an elevated PowerShell.'
}
$name='ASISTIX-Pilot-12653-WiFi-HTTPS'
$program=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'runtime/pilot-supervisor/asistix-supervisor.exe')).Path

function Get-ScopedRule($store){
    Get-NetFirewallRule -PolicyStore $store -ErrorAction Stop |
        Where-Object Name -eq $name
}

function Assert-Owner($rules){
    foreach($rule in $rules){
        if(($rule | Get-NetFirewallApplicationFilter -ErrorAction Stop).Program -ne $program){
            throw 'The rule name belongs to a different executable.'
        }
    }
}

if($Action -eq 'Status'){
    Get-ScopedRule ActiveStore | Select-Object Name,Enabled,Direction,Action,Profile
    return
}

$existing=@(Get-ScopedRule PersistentStore)
Assert-Owner $existing
if($Action -eq 'Remove'){
    $existing | Remove-NetFirewallRule -ErrorAction Stop
    if(@(Get-ScopedRule PersistentStore).Count){throw 'The pilot Wi-Fi rule remains.'}
    return
}
if($existing.Count -or @(Get-ScopedRule ActiveStore).Count){
    throw 'A pilot Wi-Fi rule already exists; use Status to review it.'
}
$ip=Get-NetIPAddress -InterfaceAlias 'Wi-Fi' -AddressFamily IPv4 -IPAddress '192.168.100.16' -ErrorAction Stop
$profile=Get-NetConnectionProfile -InterfaceIndex $ip.InterfaceIndex -ErrorAction Stop
if($ip.PrefixLength -ne 24 -or $profile.NetworkCategory -ne 'Public'){
    throw 'The authorized Wi-Fi IP, subnet or profile changed.'
}
try {
    New-NetFirewallRule -Name $name -DisplayName $name -PolicyStore PersistentStore -Program $program `
        -Direction Inbound -Action Allow -Enabled True -Profile Public -InterfaceAlias 'Wi-Fi' `
        -Protocol TCP -LocalAddress '192.168.100.16' -LocalPort 5188 -RemoteAddress '192.168.100.0/24' `
        -EdgeTraversalPolicy Block -ErrorAction Stop | Out-Null
    $applied=@(Get-ScopedRule ActiveStore)
    if($applied.Count -ne 1 -or $applied[0].Action -ne 'Allow' -or $applied[0].Enabled -ne 'True'){
        throw 'The scoped rule is not active.'
    }
    Assert-Owner $applied
    $applied | Select-Object Name,Enabled,Direction,Action,Profile
} catch {
    $detail=$_.Exception.Message
    $partial=@(Get-ScopedRule PersistentStore)
    Assert-Owner $partial
    $partial | Remove-NetFirewallRule -ErrorAction Stop
    if(@(Get-ScopedRule PersistentStore).Count){throw 'Could not confirm rollback.'}
    throw "Wi-Fi rule not applied: $detail"
}
