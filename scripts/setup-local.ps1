$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Instala Python 3.12 o 3.13 y agrégalo al PATH.' }
if (-not (Test-Path '.venv\Scripts\python.exe')) { python -m venv .venv; if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno virtual.' } }
python -m pip --python .venv\Scripts\python.exe install -r backend\requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Falló la instalación de dependencias Python.' }
if (-not (Test-Path 'backend\.env')) {
    $randomBytes = New-Object byte[] 48
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($randomBytes)
    $secret = [Convert]::ToBase64String($randomBytes)
    $rng.Dispose()
    $contents = (Get-Content backend\.env.example -Raw) -replace 'CAMBIAR-por-un-secreto-aleatorio-de-al-menos-32-caracteres', $secret
    [IO.File]::WriteAllText((Join-Path $projectRoot 'backend\.env'), $contents)
}
Push-Location backend
try { & ..\.venv\Scripts\python.exe -m app.seed; if ($LASTEXITCODE -ne 0) { throw 'Falló la carga de datos de demostración.' } }
finally { Pop-Location }
$nodePath = Join-Path $projectRoot 'tools\node.exe'
if ((Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    Push-Location frontend
    try { npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw 'Falló npm ci.' } }
    finally { Pop-Location }
} elseif (Test-Path $nodePath) {
    $env:PATH = (Join-Path $projectRoot 'tools') + ';' + $env:PATH
    Push-Location frontend
    try { & $nodePath ..\tools\package\bin\npm-cli.js ci; if ($LASTEXITCODE -ne 0) { throw 'Falló npm ci.' } }
    finally { Pop-Location }
} else { throw 'Instala Node.js 22 LTS. Luego ejecuta npm ci dentro de frontend.' }
Write-Host 'Preparado. Ejecuta scripts\start-backend.ps1 y scripts\start-frontend.ps1 en dos terminales.'
