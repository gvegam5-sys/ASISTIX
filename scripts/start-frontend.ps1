$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath (Join-Path $projectRoot 'frontend')
if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { npm.cmd run dev }
elseif (Test-Path '..\tools\node.exe') { $env:PATH = (Join-Path $projectRoot 'tools') + ';' + $env:PATH; & ..\tools\node.exe ..\tools\package\bin\npm-cli.js run dev }
else { throw 'Instala Node.js 22 LTS.' }
