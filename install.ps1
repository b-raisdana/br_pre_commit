#!/usr/bin/env pwsh

$InstallDir = $PSScriptRoot
$Python = if ($env:VIRTUAL_ENV) { Join-Path $env:VIRTUAL_ENV "Scripts\python.exe" } else { (Get-Command python -ErrorAction SilentlyContinue).Source }

Write-Host "Python: $Python"
Write-Host "Install directory: $InstallDir"

# Run as a module from the repository root: src.install imports its siblings
# (src.helper.paths), which only resolve inside the src package.
Push-Location $InstallDir
& $Python -m src.install @args
$ExitCode = $LASTEXITCODE
Pop-Location

exit $ExitCode
