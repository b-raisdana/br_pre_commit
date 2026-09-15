# 04 — Active Python Environment Design

## Overview

The tool must **not select or activate Python**. It uses whatever Python environment is active when Git executes the hook.

## Execution Flow

```
Git
  ↓
active Python (from PATH, shebang, or Git config)
  ↓
precommit_wrapper.py
```

## Requirements

### Supported Python Environments

The tool must work with **any** Python environment mechanism:

| Environment | Detection | Notes |
|-------------|-----------|-------|
| `venv` | `sys.prefix != sys.base_prefix` | Standard library |
| `virtualenv` | `hasattr(sys, 'real_prefix')` | Legacy but still used |
| Conda | `CONDA_PREFIX` in os.environ | Do NOT activate |
| system Python | Default fallback | No special handling |
| pipx/pipenv/poetry | Via PATH | Transparent |
| pyenv | Via PATH/shims | Transparent |
| Docker/container | Via PATH | Transparent |

### What the Tool Must NOT Do

- ❌ Activate Conda (`conda activate`, `source .../conda.sh`)
- ❌ Activate a virtualenv (`source venv/bin/activate`)
- ❌ Search for a "preferred" Python installation
- ❌ Hard-code a Python executable path
- ❌ Require a particular Python distribution (CPython, PyPy, etc.)
- ❌ Silently switch Python versions
- ❌ Modify `PATH` to inject a Python

### What the Tool MUST Do

- ✅ Use `sys.executable` — the Python running the hook
- ✅ Use `python -m pip` for any pip operations (not bare `pip`)
- ✅ Validate Python version at runtime (≥ 3.9)
- ✅ Report clear error if Python version unsupported
- ✅ Report clear error if required packages missing

### Installer vs Runtime

| Phase | Python Used |
|-------|-------------|
| Installer execution | Python that launched the installer (user's choice) |
| Hook execution | Python active when Git runs the hook (user's environment) |

The installer **may** use the Python that launched it, but the **installed hook** must use the active Python at execution time.

## Design: `precommit_wrapper.py` Entry Point

```python
#!/usr/bin/env python3
"""Entry point for the pre-commit hook. Uses the active Python."""

import sys
import subprocess
from pathlib import Path

MIN_PYTHON_VERSION = (3, 9)

def validate_python_version() -> None:
    if sys.version_info < MIN_PYTHON_VERSION:
        sys.exit(
            f"br_pre_commit requires Python >= {'.'.join(map(str, MIN_PYTHON_VERSION))}, "
            f"but current is {sys.version.split()[0]}. "
            f"Executable: {sys.executable}"
        )

def check_dependencies(requirements_path: Path) -> None:
    """Check required packages are importable in the active Python."""
    missing = []
    # Parse requirements.txt and check each
    # Use importlib.util.find_spec for import check
    ...

def main():
    validate_python_version()

    # Resolve paths dynamically (see 03)
    repo_root, tool_root = resolve_paths()

    # Check dependencies against active Python
    check_dependencies(tool_root / "requirements.txt")

    # Run the actual pre-commit logic
    # Use sys.executable for any subprocess calls
    result = subprocess.run(
        [sys.executable, "-m", "pre_commit", "run", ...],
        cwd=repo_root,
        ...
    )
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
```

## Using `sys.executable` for Subprocesses

```python
# GOOD — uses the same Python that's running this script
subprocess.run([sys.executable, "-m", "pre_commit", "run", ...])

# GOOD — uses python -m pip from the active environment
subprocess.run([sys.executable, "-m", "pip", "install", "-r", requirements_path])

# BAD — assumes bare 'pip' exists and points to the right environment
subprocess.run(["pip", "install", "-r", requirements_path])

# BAD — hardcodes python3
subprocess.run(["python3", "-m", "pre_commit", "run", ...])
```

## Error Messages

### Unsupported Python Version

```
ERROR: br_pre_commit requires Python >= 3.9
       Current: Python 3.8.10 (/usr/bin/python3)

       Please use a supported Python environment.
```

### Missing Packages (see 05)

```
ERROR: Required packages are missing from the active Python environment.

Install them with:

    python -m pip install -r "/absolute/path/to/br_pre_commit/requirements.txt"

Missing packages:
    - pre-commit
    - ruff
    - mypy
```

## Verification Checklist

- [ ] Hook runs with system Python
- [ ] Hook runs with venv
- [ ] Hook runs with virtualenv
- [ ] Hook runs with Conda (without activation)
- [ ] Hook runs with pyenv
- [ ] Hook runs with pipx-installed pre-commit
- [ ] Python < 3.9 → clear error with version and executable path
- [ ] Uses `sys.executable` for all subprocess calls
- [ ] Uses `python -m pip` not bare `pip`
- [ ] No conda activation code
- [ ] No virtualenv activation code
