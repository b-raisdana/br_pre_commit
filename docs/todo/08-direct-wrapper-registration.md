# 08 — Direct `precommit_wrapper.py` Registration Design

## Overview

Eliminate `run` and `run.ps1` as execution shims. The final design should register the pre-commit hook directly to the Python implementation (`src/br_pre_commit/precommit_wrapper.py`) without requiring intermediate shell scripts.

## Requirements

### Elimination Targets

| Shim | Current Role | Replacement |
|------|--------------|-------------|
| `run` (POSIX shell) | Entry point for Linux/WSL hook | Direct `python -m br_pre_commit.precommit_wrapper` |
| `run.ps1` (PowerShell) | Entry point for Windows hook | Direct `python -m br_pre_commit.precommit_wrapper` |

### Hook Registration

The hook should ultimately execute:
```
src/br_pre_commit/precommit_wrapper.py
```
via:
```
python -m br_pre_commit.precommit_wrapper
```
without requiring:
```
./run
./run.ps1
```

### Cross-Platform Hook

The same hook design works on both platforms:
- POSIX: `#!/usr/bin/env sh` + `exec python -m br_pre_commit.precommit_wrapper "$@"`
- Windows: `#!/usr/bin/env pwsh` + `python -m br_pre_commit.precommit_wrapper $args`

## Design: Direct Module Execution

### Why `python -m br_pre_commit.precommit_wrapper`?

1. **No path assumptions** — Python finds the module via `sys.path`
2. **Works from any directory** — Git runs hook from repo root
3. **Uses active Python** — `python` resolves to the environment's Python
4. **No intermediate files** — No `run`/`run.ps1` to maintain or sync
5. **Standard Python pattern** — `-m` is the standard way to run modules

### Module Structure

```
br_pre_commit/
├── __init__.py
├── precommit_wrapper.py    # Main entry point
├── gap_analyzer.py
├── hook_installer.py
├── install.py              # Installer entry point
├── requirements.txt        # Runtime dependencies
└── ...
```

### `precommit_wrapper.py` Responsibilities

```python
# src/br_pre_commit/precommit_wrapper.py
"""Main entry point for the pre-commit hook."""

import sys
from pathlib import Path

def main():
    # 1. Validate Python version (≥ 3.9)
    validate_python_version()

    # 2. Resolve repository and tool roots dynamically
    repo_root, tool_root = resolve_paths()

    # 3. Check dependencies against active Python
    check_dependencies(tool_root / "requirements.txt")

    # 4. Run the actual pre-commit logic
    # Delegate to pre_commit package or internal implementation
    return run_pre_commit(repo_root, tool_root)

if __name__ == "__main__":
    sys.exit(main())
```

### Removing `run` and `run.ps1`

**Current (to be removed):**
```
.git/hooks/pre-commit → ./run → python -m br_pre_commit.precommit_wrapper
.git/hooks/pre-commit → ./run.ps1 → python -m br_pre_commit.precommit_wrapper
```

**New (direct):**
```
.git/hooks/pre-commit → python -m br_pre_commit.precommit_wrapper
```

### Migration Steps

1. Update hook installer to generate direct hook (see 07)
2. Update gap analyzer to flag `run`/`run.ps1` as obsolete (see 06)
3. Remove `run` and `run.ps1` from repository
4. Update documentation and README
5. Verify installer works without them

### Backward Compatibility

During transition, the installer should:
- Detect hooks pointing to `run`/`run.ps1` → migrate automatically
- Not require `run`/`run.ps1` to exist
- Gap analyzer reports them as WARNING with remediation

## Verification Checklist

- [ ] Hook executes `python -m br_pre_commit.precommit_wrapper` directly
- [ ] No `run` file in repository
- [ ] No `run.ps1` file in repository
- [ ] Hook works on Linux/WSL (POSIX)
- [ ] Hook works on Windows (PowerShell)
- [ ] Gap analyzer flags obsolete shims
- [ ] Installer migrates old hooks automatically
- [ ] `precommit_wrapper.py` handles all responsibilities
- [ ] No path assumptions in hook
- [ ] Works from any working directory
