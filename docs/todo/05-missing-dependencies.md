# 05 — Missing Dependencies Design

## Overview

Before running the actual pre-commit implementation, the tool must detect missing required Python packages, check against the currently active Python, and produce a clear error with a copy/pasteable installation command.

## Requirements

### Detection

- Check required packages against the **currently active Python** (`sys.executable`)
- Do NOT automatically install missing dependencies
- Produce a clear, actionable error message
- Show the missing packages
- Show a directly copy/pasteable installation command
- The command must reference the repository's actual `requirements.txt` using its **resolved absolute path**

### Error Format

```
Required packages are missing from the active Python environment.

Install them with:

    python -m pip install -r "/absolute/path/to/br_pre_commit/requirements.txt"

Missing packages:
    - pre-commit
    - ruff
    - mypy
    - pytest
```

### Use `python -m pip`

Prefer `python -m pip` over assuming a `pip` executable is available.

### Requirements Source

The `requirements.txt` is located at the `br_pre_commit` tool root (resolved dynamically at runtime, not hardcoded).

## Design: Dependency Checker

```python
# In precommit_wrapper.py or a shared module
import sys
import subprocess
import importlib.util
from pathlib import Path
from typing import List, Tuple

def parse_requirements(requirements_path: Path) -> List[str]:
    """Parse requirements.txt, return list of package names."""
    packages = []
    for line in requirements_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            # Extract package name (before version specifiers)
            name = line.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].split("[")[0]
            packages.append(name.strip())
    return packages

def check_importable(package_name: str) -> bool:
    """Check if a package is importable in the current Python."""
    try:
        # Normalize package name for import (hyphens → underscores)
        import_name = package_name.replace("-", "_")
        spec = importlib.util.find_spec(import_name)
        return spec is not None
    except (ImportError, AttributeError, ModuleNotFoundError):
        return False

def check_dependencies(requirements_path: Path) -> Tuple[bool, List[str]]:
    """Check all required packages. Returns (all_ok, missing_list)."""
    if not requirements_path.exists():
        return False, [f"requirements.txt not found at {requirements_path}"]

    required = parse_requirements(requirements_path)
    missing = [pkg for pkg in required if not check_importable(pkg)]
    return len(missing) == 0, missing

def format_missing_error(missing: List[str], requirements_path: Path) -> str:
    """Format the error message with copy/pasteable command."""
    abs_path = requirements_path.resolve()
    cmd = f'python -m pip install -r "{abs_path}"'

    lines = [
        "Required packages are missing from the active Python environment.",
        "",
        "Install them with:",
        "",
        f"    {cmd}",
        "",
        "Missing packages:",
    ]
    for pkg in missing:
        lines.append(f"    - {pkg}")

    return "\n".join(lines)

def main():
    # ... resolve paths ...
    tool_root = resolve_tool_root()
    requirements_path = tool_root / "requirements.txt"

    ok, missing = check_dependencies(requirements_path)
    if not ok:
        sys.exit(format_missing_error(missing, requirements_path))

    # ... continue with pre-commit execution ...
```

## Handling Special Cases

### Editable Installs / Local Packages

If `requirements.txt` contains `-e .` or local paths, the checker should:
- Skip non-PyPI entries for import checking
- Still include them in the install command (pip handles them)

### Version Constraints

The checker only verifies **importability**, not version matching. Version conflicts will surface at runtime from `pre-commit` itself.

### Optional Dependencies

If some packages are truly optional (e.g., only needed for certain hooks), they should be in a separate `requirements-optional.txt` or marked in `requirements.txt` with a comment.

## Integration Point

The dependency check runs **early** in `precommit_wrapper.py`, before any other logic:

```python
def main():
    # 1. Validate Python version (see 04)
    validate_python_version()

    # 2. Resolve paths
    repo_root, tool_root = resolve_paths()

    # 3. Check dependencies — FAIL FAST with clear error
    ok, missing = check_dependencies(tool_root / "requirements.txt")
    if not ok:
        sys.exit(format_missing_error(missing, tool_root / "requirements.txt"))

    # 4. Continue with pre-commit execution
    ...
```

## Verification Checklist

- [ ] Missing packages detected correctly
- [ ] Error shows absolute path to requirements.txt
- [ ] Error command uses `python -m pip`
- [ ] Error is copy/pasteable (quoted path handles spaces)
- [ ] No auto-install attempted
- [ ] Check runs against active Python (`sys.executable`)
- [ ] Works with venv, virtualenv, Conda, system Python
- [ ] Handles requirements.txt with version specifiers
- [ ] Handles requirements.txt with comments and blank lines
- [ ] Clear error when requirements.txt not found
