#Requires -Version 5.1
param([Parameter(Mandatory)][ValidateSet('Apply','Remove','Status')][string]$Action)

$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if ($Action -ne 'Status' -and -not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run Apply or Remove from an elevated PowerShell.'
}

$program = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'runtime/pilot-python/asistix-face.exe')).Path
$ruleName = 'ASISTIX-Pilot-12653-Block-External'
$managedNames = @($ruleName)
$destinations = @('Any')

function Get-PilotRules($store, $names) {
    Get-NetFirewallRule -PolicyStore $store -ErrorAction Stop |
        Where-Object { $_.Name -in $names }
}

function Assert-PilotOwner($entries) {
    foreach ($entry in $entries) {
        $filter = $entry | Get-NetFirewallApplicationFilter -ErrorAction Stop
        if ($filter.Program -ne $program) {
            throw "Rule name belongs to another program: $($entry.Name)"
        }
    }
}

function Remove-PilotRules($names) {
    $entries = @(Get-PilotRules PersistentStore $names)
    Assert-PilotOwner $entries
    foreach ($entry in $entries) {
        $entry | Remove-NetFirewallRule -ErrorAction Stop
    }
    $remaining = @(Get-PilotRules PersistentStore $names)
    if ($remaining.Count -ne 0) {
        throw ('Pilot rules remain: ' + ($remaining.Name -join ', '))
    }
}

if ($Action -eq 'Status') {
    Get-PilotRules ActiveStore $managedNames |
        ForEach-Object {
            [pscustomobject]@{
                Name = $_.Name
                Enabled = $_.Enabled
                Direction = $_.Direction
                Action = $_.Action
                Program = ($_ | Get-NetFirewallApplicationFilter -ErrorAction Stop).Program
                RemoteAddress = ($_ | Get-NetFirewallAddressFilter -ErrorAction Stop).RemoteAddress -join ', '
            }
        }
    return
}
if ($Action -eq 'Remove') {
    Remove-PilotRules $managedNames
    Write-Output 'No pilot rules remain in PersistentStore.'
    return
}

$existing = @(Get-PilotRules PersistentStore $managedNames)
Assert-PilotOwner $existing
if ($existing.Count -ne 0) {
    throw 'A pilot rule already exists. Run -Action Remove, then retry Apply.'
}
if (@(Get-PilotRules ActiveStore $managedNames).Count -ne 0) {
    throw 'A pilot rule already exists in ActiveStore. Review the effective policy.'
}

try {
    $created = @(New-NetFirewallRule -PolicyStore PersistentStore -Name $ruleName -DisplayName $ruleName -Profile Any -Enabled True -Direction Outbound -Action Block -Program $program -RemoteAddress $destinations -ErrorAction Stop -ErrorVariable createErrors)
    if ($created.Count -ne 1 -or $createErrors) {
        throw 'Windows did not confirm exactly one rule without errors.'
    }
    $active = @(Get-PilotRules ActiveStore @($ruleName))
    if ($active.Count -ne 1 -or $active[0].Enabled -ne 'True' -or
        $active[0].Direction -ne 'Outbound' -or $active[0].Action -ne 'Block') {
        throw 'The outbound block is not active.'
    }
    Assert-PilotOwner $active
    $effective = @($active[0] | Get-NetFirewallAddressFilter -ErrorAction Stop |
        Select-Object -ExpandProperty RemoteAddress)
    if (Compare-Object -ReferenceObject $destinations -DifferenceObject $effective) {
        throw ('Unexpected remote addresses in ActiveStore: ' + ($effective -join ', '))
    }
    $active | Select-Object Name, Enabled, Direction, Action
} catch {
    $failure = $_.Exception.Message
    try {
        # Read back by name even if New-NetFirewallRule failed before returning.
        Remove-PilotRules @($ruleName)
        if (@(Get-PilotRules ActiveStore @($ruleName)).Count -ne 0) {
            throw 'The pilot rule remains in ActiveStore.'
        }
    } catch {
        throw "Apply failed: $failure. Rollback could not be verified: $($_.Exception.Message). Keep the pilot stopped and run -Action Status."
    }
    throw "Apply failed and rollback was verified: $failure"
}
