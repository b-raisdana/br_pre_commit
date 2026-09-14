#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Runs the br_pre_commit precommit wrapper.

.DESCRIPTION
    Entry point for the pre-commit hook. Sets up environment variables and executes the Python wrapper.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Get the tool root (directory containing this script)
$ToolRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ToolRoot = Resolve-Path $ToolRoot

# Get repo root from environment or git
$RepoRoot = $env:BR_PRE_COMMIT_REPO_ROOT
if (-not $RepoRoot) {
    $RepoRoot = git rev-parse --show-toplevel
}
$env:BR_PRE_COMMIT_REPO_ROOT = $RepoRoot

# Execute the Python wrapper
python "$ToolRoot/src/br_pre_commit/precommit_wrapper.py" @args
