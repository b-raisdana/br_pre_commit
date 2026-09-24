#!/usr/bin/env pwsh

$InstallDir = $PSScriptRoot
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source

Write-Host "Python: $Python"
Write-Host "Install directory: $InstallDir"

& $Python "$InstallDir/src/install.py" @args
exit $LASTEXITCODE
