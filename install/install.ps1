#!/usr/bin/env pwsh
$InstallDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Get-Command python | Select-Object -ExpandProperty Source
Write-Output "Python: $Python"
Write-Output "Install directory: $InstallDir"
& $Python (Join-Path $InstallDir "install.py") @args
exit $LASTEXITCODE
