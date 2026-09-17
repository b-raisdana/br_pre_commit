# 13 — Hook Independence from Installer Location

## Overview

The installed hook must **not assume that the installer, submodule, or Python package remains at the path used during installation**. It must resolve the current repository/submodule location dynamically at runtime.

## Requirements

### Problem

Users can:
- Move the repository to a different location
- Clone it elsewhere (different path, different OS)
- Clone it on another OS (Windows ↔ Linux/WSL)
- Change the submodule location
- Switch branches (submodule at different commit/path)

The hook must continue to work in all these scenarios.

### Solution: Dynamic Resolution at Runtime

The hook (or its Python entry point) must resolve paths **at execution time**, not at install time.

```python
# In precommit_wrapper.py
def resolve_paths() -> tuple[Path, Path]:
    """
    Resolve repository root and tool root dynamically.
    Called every time the hook runs.
    """
    # 1. Repository root - always works from any subdirectory
    repo_root = get_git_repo_root()

    # 2. Tool root - resolve via submodule or package
    tool_root = get_tool_root(repo_root)

    return repo_root, tool_root

def get_git_repo_root() -> Path:
    """Get Git repository root using git command."""
    import subprocess
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True
    )
    return Path(result.stdout.strip())

def get_tool_root(repo_root: Path) -> Path:
    """
    Resolve br_pre_commit tool root.
    Tries multiple strategies in order.
    """
    # Strategy 1: Git submodule status
    tool_root = resolve_via_submodule(repo_root)
    if tool_root:
        return tool_root

    # Strategy 2: Relative to this script (if installed as package)
    tool_root = resolve_via_package_location()
    if tool_root:
        return tool_root

    # Strategy 3: Common locations (fallback)
    tool_root = resolve_via_common_paths(repo_root)
    if tool_root:
        return tool_root

    raise RuntimeError("Cannot locate br_pre_commit tool root")

def resolve_via_submodule(repo_root: Path) -> Optional[Path]:
    """Resolve via git submodule status."""
    import subprocess
    result = subprocess.run(
        ["git", "submodule", "status", "br_pre_commit"],
        cwd=repo_root, capture_output=True, text=True
    )
    if result.returncode == 0 and result.stdout.strip():
        # Output: <commit> <path> <ref>
        parts = result.stdout.strip().split()
        if len(parts) >= 2:
            candidate = (repo_root / parts[1]).resolve()
            if (candidate / "src" / "br_pre_commit").exists():
                return candidate
    return None

def resolve_via_package_location() -> Optional[Path]:
    """Resolve via __file__ if running as installed package."""
    try:
        # This file: src/precommit_wrapper.py
        # Tool root: parent of src/br_pre_commit
        current_file = Path(__file__).resolve()
        # Navigate up to find br_pre_commit root
        for parent in current_file.parents:
            if (parent / "src" / "br_pre_commit" / "precommit_wrapper.py").exists():
                return parent
            if (parent / "requirements.txt").exists() and (parent / "src" / "br_pre_commit").exists():
                return parent
    except (NameError, AttributeError):
        pass
    return None

def resolve_via_common_paths(repo_root: Path) -> Optional[Path]:
    """Fallback: check common submodule locations."""
    common = [
        "br_pre_commit",
        "tools/br_pre_commit",
        ".br_pre_commit",
        "vendor/br_pre_commit",
        "deps/br_pre_commit",
    ]
    for rel in common:
        candidate = (repo_root / rel).resolve()
        if (candidate / "src" / "br_pre_commit").exists():
            return candidate
    return None
```

### What the Hook Must NOT Contain

| Anti-Pattern | Why It Fails |
|--------------|--------------|
| Absolute repo path | Breaks on move/clone |
| Absolute tool path | Breaks on move/clone |
| Hardcoded Python path | Breaks on different OS/env |
| Conda activation | Breaks on different env |
| Virtualenv activation | Breaks on different env |
| `sys.path` manipulation at install time | Breaks on move |

### Hook Template (No Paths)

```bash
#!/usr/bin/env sh
# br_pre_commit hook
# installed: 2026-09-15T10:30:00Z
# mode: dual
# tool_root: dynamic
# python: active
exec python -m br_pre_commit.precommit_wrapper "$@"
```

### Runtime Behavior

```
User commits
    ↓
Git runs .git/hooks/pre-commit
    ↓
Hook: exec python -m br_pre_commit.precommit_wrapper
    ↓
Python finds br_pre_commit module via sys.path
    ↓
precommit_wrapper.py runs resolve_paths()
    ↓
git rev-parse --show-toplevel → repo_root
git submodule status br_pre_commit → tool_root
    ↓
All paths resolved for current state
    ↓
pre-commit executes with correct paths
```

### Cross-OS Clone Scenario

1. Developer clones repo on Linux at `/home/user/project`
2. Runs `python -m br_pre_commit.install` → hook created
3. Pushes to remote
4. Same developer clones on Windows at `C:\project`
5. Runs `python -m br_pre_commit.install` → hook created (Windows version)
6. Both hooks work because they resolve paths at runtime

### Submodule Location Change

```
Original: project/br_pre_commit/
Changed:  project/tools/br_pre_commit/
```

1. User moves submodule, commits, pushes
2. Other developers pull, run `git submodule update`
3. Next commit: hook runs `git submodule status br_pre_commit`
4. Gets new path → resolves correctly → works

### Branch Switching

```
Branch A: submodule at commit abc123, path br_pre_commit/
Branch B: submodule at commit def456, path tools/br_pre_commit/
```

1. User switches branch: `git switch branch-b`
2. Runs `git submodule update`
3. Next commit: hook resolves new path → works

## Verification Checklist

- [ ] Hook contains no absolute paths
- [ ] Hook contains no hardcoded Python path
- [ ] Hook contains no conda/virtualenv activation
- [ ] `precommit_wrapper.py` resolves repo root via `git rev-parse`
- [ ] `precommit_wrapper.py` resolves tool root via `git submodule status`
- [ ] Falls back to package location if submodule not found
- [ ] Falls back to common paths as last resort
- [ ] Works after `mv project /new/location`
- [ ] Works after `git clone` on different OS
- [ ] Works after submodule path change
- [ ] Works after branch switch with different submodule path
- [ ] Works after `git submodule update`
- [ ] Clear error if tool root cannot be resolved
