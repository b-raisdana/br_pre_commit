#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Installs the pre-commit hook for the current repository.

.DESCRIPTION
    Creates a pre-commit hook in .git/hooks/pre-commit that runs the br_pre_commit tool.
    Supports both native Windows execution and WSL execution.

.PARAMETER RepoRoot
    The root directory of the git repository. Defaults to the current repository's toplevel.

.EXAMPLE
    ./install.ps1

.EXAMPLE
    ./install.ps1 -RepoRoot "C:\path\to\repo"
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$RepoRoot = (git rev-parse --show-toplevel)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Get the tool root (directory containing this script)
$ToolRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ToolRoot = Resolve-Path $ToolRoot

# Resolve repo root
$RepoRoot = Resolve-Path $RepoRoot

# Get git directory
$GitDir = git -C $RepoRoot rev-parse --absolute-git-dir
$HookPath = Join-Path $GitDir "hooks" "pre-commit"

# Create the hook content as a PowerShell script
$HookContent = @"
#!/usr/bin/env pwsh
# br_pre_commit pre-commit hook
\$env:BR_PRE_COMMIT_REPO_ROOT = '$($RepoRoot.Replace("'", "''"))'
\$env:BR_PRE_COMMIT_TOOL_ROOT = '$($ToolRoot.Replace("'", "''"))'

# Check if running in WSL or if wsl.exe is available
if (Test-Path "wsl.exe" -PathType Command) {
    # Running in WSL or wsl.exe available - use WSL to run the hook
    \$wslEnv = "BR_PRE_COMMIT_REPO_ROOT/p:BR_PRE_COMMIT_TOOL_ROOT/p"
    if (\$env:GIT_INDEX_FILE) {
        \$wslEnv += ":GIT_INDEX_FILE/p"
    }
    if (\$env:WSLENV) {
        \$wslEnv += ":\$env:WSLENV"
    }
    \$env:WSLENV = \$wslEnv
    & wsl.exe -d Ubuntu-24.04 -- bash -lc '
        source ~/miniconda3/etc/profile.d/conda.sh &&
        conda activate tf &&
        cd "$env:BR_PRE_COMMIT_REPO_ROOT" &&
        exec "$env:BR_PRE_COMMIT_TOOL_ROOT/run"
    '
} else {
    # Native Windows execution
    & "$env:BR_PRE_COMMIT_TOOL_ROOT/run.ps1"
}
"@

# Write the hook
$HookContent | Set-Content -Path $HookPath -Encoding UTF8

# Make it executable (for WSL/Git Bash compatibility)
if (Test-Path "wsl.exe" -PathType Command) {
    wsl.exe chmod +x $HookPath
}

Write-Host "Installed $HookPath -> $ToolRoot/run.ps1"
