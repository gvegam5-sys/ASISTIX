$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$source=(Get-Content -Raw -Encoding utf8 (Join-Path $root 'firewall-piloto.ps1')).Replace('$PSScriptRoot', "'" + $root + "'")
$source=$source.Replace('if ($Action -ne ''Status'' -and -not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {','if ($false) {')
$run=[ScriptBlock]::Create($source)
$script:rules=@{}
function Get-NetFirewallRule { [CmdletBinding()] param($PolicyStore) $script:rules.Values }
function Get-NetFirewallApplicationFilter { [CmdletBinding()] param([Parameter(ValueFromPipeline)]$Rule) process { [pscustomobject]@{Program=$Rule.Program} } }
function Get-NetFirewallAddressFilter { [CmdletBinding()] param([Parameter(ValueFromPipeline)]$Rule) process { [pscustomobject]@{RemoteAddress=$Rule.RemoteAddress} } }
function Remove-NetFirewallRule { [CmdletBinding()] param([Parameter(ValueFromPipeline)]$Rule) process { $script:rules.Remove($Rule.Name) } }
function New-NetFirewallRule {
 [CmdletBinding()] param($Name,$DisplayName,$PolicyStore,$Profile,$Enabled,$Direction,$Action,$Program,$RemoteAddress)
 $entry=[pscustomobject]@{Name=$Name;Enabled=$Enabled;Direction=$Direction;Action=$Action;Program=$Program;RemoteAddress=$RemoteAddress}
 $script:rules[$Name]=$entry
 if($script:failCreation){throw 'simulated error after persistent write'}
 $entry
}
$old='ASISTIX-Pilot-1252-Block-IPv4'
$script:rules['unrelated']=[pscustomobject]@{Name='unrelated';Program='other.exe'}
$script:rules[$old]=[pscustomobject]@{Name=$old;Program='other.exe'}
try { & $run -Action Remove; throw 'expected foreign rule error' } catch { if($_.Exception.Message -notlike '*another program*'){throw} }
if($script:rules.Count -ne 2){throw 'foreign rule changed'}
$script:rules[$old].Program=Join-Path $root 'runtime/pilot-python/asistix-face.exe'
& $run -Action Remove
if($script:rules.Count -ne 1){throw 'legacy cleanup did not preserve unrelated rule'}
$script:failCreation=$true
try { & $run -Action Apply; throw 'expected creation error' } catch { if($_.Exception.Message -notlike '*rollback was verified*'){throw} }
if($script:rules.Count -ne 1){throw 'rollback left a partial rule'}
$script:failCreation=$false
& $run -Action Apply
if($script:rules.Count -ne 2 -or $script:rules['ASISTIX-Pilot-1252-Block-External'].RemoteAddress -ne 'Any'){throw 'missing consolidated rule'}
& $run -Action Remove
if($script:rules.Count -ne 1){throw 'reversal failed'}
'Simulated legacy cleanup, foreign-rule protection, failure after write, successful apply and reversal: passed.'
