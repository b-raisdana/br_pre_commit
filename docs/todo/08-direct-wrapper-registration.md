# 08 — Cross-Platform `run` Script Design

## Overview

The `run` (POSIX) and `run.ps1` (PowerShell) scripts in the repository root serve as cross-platform launchers for the pre-commit tool. They set up environment variables and dispatch to the Python implementation (`src/precommit_wrapper.py`) based on the operating system.

## Requirements

### Launcher Scripts

| Script | Platform | Role |
|--------|----------|------|
| `run` (POSIX shell) | Linux, WSL, macOS | Entry point for POSIX environments |
| `run.ps1` (PowerShell) | Windows native | Entry point for Windows environments |

### Hook Registration

The Git hook installed by the installer executes `precommit_wrapper.py` directly via `python`. For manual invocation or CI, the `run` / `run.ps1` scripts provide a consistent entry point:

```
./run                    # POSIX: exec python src/precommit_wrapper.py
./run.ps1                # Windows: python src/precommit_wrapper.py
```

### Cross-Platform Dispatch

The `run` script detects the platform and dispatches accordingly:

- **Linux/WSL**: `exec python "$BR_PRE_COMMIT_TOOL_ROOT/src/precommit_wrapper.py" "$@"`
- **Windows (via `run`)**: delegates to `run.ps1` via PowerShell
- **`run.ps1`**: `python "$BR_PRE_COMMIT_TOOL_ROOT/src/precommit_wrapper.py" $args`

## Design: `run` Script

### Why a launcher script?

1. **Centralized entry point** — One script for all platforms
2. **Environment setup** — Sets `BR_PRE_COMMIT_TOOL_ROOT` and other variables
3. **Platform dispatch** — Routes to correct implementation per OS
4. **Consistent interface** — Same invocation pattern regardless of platform

### Module Structure

```
repo-root/
├── run               # POSIX launcher
├── run.ps1           # PowerShell launcher
├── src/
│   ├── precommit_wrapper/
│   │   ├── __main__.py    # Main entry point
│   │   └── config.py
│   ├── backup/
│   │   ├── __main__.py
│   │   ├── common.py
│   │   └── recover.py
│   ├── sync_skills/
│   │   ├── __main__.py
│   │   ├── core.py
│   │   ├── sync.py
│   │   └── utils.py
│   ├── ratchet/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── baseline.py
│   │   ├── details.py
│   │   ├── gate.py
│   │   └── tools.py
│   └── ...
└── ...
```

### `precommit_wrapper.py` Responsibilities

```python
# src/precommit_wrapper.py
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
    return run_pre_commit(repo_root, tool_root)

if __name__ == "__main__":
    sys.exit(main())
```

### Backward Compatibility

During transition, the installer should:
- Detect hooks pointing to `run`/`run.ps1` → migrate automatically
- Support `run`/`run.ps1` as valid entry points
- Gap analyzer reports legacy hooks as WARNING with remediation

## Verification Checklist

- [ ] `run` executes `python src/precommit_wrapper.py` on Linux/WSL
- [ ] `run.ps1` executes `python src/precommit_wrapper.py` on Windows
- [ ] `run` delegates to `run.ps1` on Windows (MINGW/MSYS/CYGWIN)
- [ ] `run` is executable
- [ ] Hook works on Linux/WSL (POSIX)
- [ ] Hook works on Windows (PowerShell)
- [ ] Gap analyzer correctly identifies launcher scripts
- [ ] `precommit_wrapper.py` handles all responsibilities
- [ ] Works from any working directory
