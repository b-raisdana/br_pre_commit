#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$BrPreCommitDir = $PSScriptRoot
$UserRepoDir = (Get-Location).Path

$Python = if ($env:VIRTUAL_ENV) { Join-Path $env:VIRTUAL_ENV "Scripts\python.exe" } else { (Get-Command python -ErrorAction SilentlyContinue).Source }

Write-Host "Python: $Python"
Write-Host "br_pre_commit repository directory: $BrPreCommitDir"
Write-Host "User repository directory: $UserRepoDir"

if ([string]::IsNullOrWhiteSpace($Python) -or -not (Test-Path -Path $Python -PathType Leaf)) {
    Write-Error "ERROR: no usable Python interpreter; activate a virtual environment first."
    exit 1
}

# Run as a module from the repository root: src.install imports its siblings
# (src.helper.paths), which only resolve inside the src package.
Push-Location $BrPreCommitDir

& $Python -m src.install $UserRepoDir @args
$ExitCode = $LASTEXITCODE

Pop-Location

exit $ExitCode
