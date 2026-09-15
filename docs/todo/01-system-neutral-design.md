# 01 — System Neutral Design

## Overview

The `br_pre_commit` tool must treat native Linux and WSL identically, support native Windows independently, and never invoke WSL from Windows.

## Principles

### Platform Equality

- **Linux and WSL are identical** — no code paths distinguish between them unless technically necessary (e.g., filesystem case-sensitivity, specific WSLg/WSL2 behaviors)
- **Windows is independent** — native Windows uses its own Python executable, paths, and conventions
- **No cross-invocation** — Windows never calls into WSL (`wsl.exe`, `bash.exe`, etc.); Linux/WSL never depends on Windows executables (`.exe`, `.bat`, `.ps1`)

### No Hard-Coded Assumptions

The following must **never** be hard-coded:

| Category | Examples |
|----------|----------|
| Usernames | `brais`, `user`, `Administrator` |
| Linux home paths | `/home/brais`, `/home/user` |
| Windows drive letters | `C:\`, `D:\` |
| Conda paths | `/opt/conda`, `~/miniconda3`, `C:\Users\...\Anaconda3` |
| Virtualenv paths | `~/.venv`, `C:\Users\...\venv` |
| Python executables | `/usr/bin/python3`, `python.exe`, `python3.11` |

### Dynamic Path Resolution

All repository and tool paths must be resolved at runtime:

- Repository root: `git rev-parse --show-toplevel`
- Submodule location: `git submodule status br_pre_commit` or `.gitmodules` parsing
- Tool root: relative to the hook script or installer location

### Portable Python Standard Library

Prefer `os`, `pathlib`, `platform`, `subprocess`, `sys` over OS-specific logic. Use `shutil.which()` for executable discovery. Use `pathlib.Path` for all path manipulation.

## Decision: Linux/WSL Unification

```python
# GOOD - treats Linux and WSL the same
import platform
is_windows = platform.system() == "Windows"
is_posix = not is_windows  # covers Linux, WSL, macOS
```

```python
# BAD - distinguishes WSL unnecessarily
import platform
if "microsoft" in platform.release().lower():
    # WSL-specific code
```

## Rationale

- Simpler maintenance: one POSIX code path
- WSL is Linux-compatible; differences are runtime environment, not API
- Avoids bugs where WSL is treated differently from native Linux
- Consistent behavior across developer machines
