# 02 — Cross-Platform Installation Design

## Overview

Installation must work correctly on Linux, WSL, and native Windows + Git. The installer must correctly identify the target Git repository, register the project's active Git hook, and work when `br_pre_commit` is included as a Git submodule.

## Requirements

### Platform Support Matrix

| Platform | Installer | Hook Format | Python Environment |
|----------|-----------|-------------|-------------------|
| Linux native | `install.sh` / Python installer | POSIX shell (shebang) | Active Python in PATH |
| WSL | `install.sh` / Python installer | POSIX shell (shebang) | Active Python in PATH |
| Windows native | `install.ps1` / Python installer | PowerShell (shebang) | Active Python in PATH |

### Git Repository Detection

The installer must:
1. Find the Git repository root: `git rev-parse --show-toplevel`
2. Verify it's a valid Git repo (`.git` directory exists)
3. Handle worktrees correctly (`.git` may be a file pointing to the main repo)

### Submodule Detection

The installer must:
1. Detect `br_pre_commit` as a submodule: `git submodule status br_pre_commit`
2. Parse `.gitmodules` for the submodule path
3. **Never assume a fixed path** — the submodule can be at any location
4. Resolve the absolute path to the submodule at install time

### Hook Registration

The installer must:
1. Create/update `.git/hooks/pre-commit` with the correct entry point
2. Make the hook executable on POSIX (`chmod +x`)
3. On Windows, ensure PowerShell execution policy allows the hook
4. Record installation metadata in the hook (mode, timestamp, tool root)

### Idempotency

Running the installer multiple times must:
- Detect an existing correct hook → no-op (report "already installed")
- Detect an outdated hook → update in place
- Detect a conflicting hook → preserve user's hook, report conflict, suggest migration
- Never duplicate hook content

### No Dependency on `run` / `run.ps1`

The installer must not require `run` or `run.ps1` to exist. The hook should point directly to the Python implementation.

## Design: Python-Native Installer

```
install.py (entry point)
    ↓
GitRepoResolver       → finds repo root, worktree handling
SubmoduleResolver     → finds br_pre_commit submodule path
HookGenerator         → creates hook content for current platform
HookInstaller         → writes hook, sets permissions, validates
GapAnalyzer           → validates installation (see 06)
```

### Entry Points

- `python -m br_pre_commit.install` — primary entry point
- `install.sh` — minimal POSIX wrapper: `exec python -m br_pre_commit.install "$@"`
- `install.ps1` — minimal PowerShell wrapper: `python -m br_pre_commit.install $args`

### Submodule Path Resolution

```python
def resolve_submodule_path(repo_root: Path) -> Path:
    # 1. Try git submodule status
    result = subprocess.run(
        ["git", "submodule", "status", "br_pre_commit"],
        cwd=repo_root, capture_output=True, text=True
    )
    if result.returncode == 0 and result.stdout.strip():
        # Output: <commit> <path> <ref>
        parts = result.stdout.strip().split()
        if len(parts) >= 2:
            return (repo_root / parts[1]).resolve()

    # 2. Fallback: parse .gitmodules
    gitmodules = repo_root / ".gitmodules"
    if gitmodules.exists():
        # Parse for path = br_pre_commit
        ...

    # 3. Fallback: common locations (for backward compat)
    for candidate in ["br_pre_commit", "tools/br_pre_commit", ".br_pre_commit"]:
        p = repo_root / candidate
        if (p / "src" / "br_pre_commit").exists():
            return p.resolve()

    raise InstallError("br_pre_commit submodule not found")
```

## Migration from Old Design

| Old Behavior | New Behavior |
|--------------|--------------|
| Hook → `./run` | Hook → `python -m br_pre_commit.precommit_wrapper` |
| Hook → `./run.ps1` | Hook → `python -m br_pre_commit.precommit_wrapper` |
| Hardcoded paths | Dynamic path resolution at hook runtime |
| Separate POSIX/Windows logic | Unified Python installer, platform-specific hook template |

## Verification Checklist

- [ ] Fresh install on Linux native
- [ ] Fresh install on WSL
- [ ] Fresh install on Windows native (Git for Windows)
- [ ] Submodule at root: `br_pre_commit/`
- [ ] Submodule nested: `tools/br_pre_commit/`
- [ ] Submodule in superproject (project is also a submodule)
- [ ] Re-install is idempotent
- [ ] Existing hook preserved/composed
- [ ] Hook executable on POSIX
- [ ] Hook runs on Windows PowerShell
- [ ] Gap analyzer passes (see 06)
