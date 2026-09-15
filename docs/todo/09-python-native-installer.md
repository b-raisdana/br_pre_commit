# 09 — Python-Native Installer Design

## Overview

Keep as much installer logic as possible inside Python. The installer should be implemented primarily in Python rather than duplicating installation logic in shell scripts.

## Requirements

### Architecture

```
installer entry point (minimal shell/PS1)
        ↓
Python installer (all installation logic)
        ↓
all installation operations
```

### Minimal Platform Launchers

**`install.sh` (POSIX):**
```bash
#!/usr/bin/env sh
# Minimal launcher - delegates to Python installer
exec python -m br_pre_commit.install "$@"
```

**`install.ps1` (Windows):**
```powershell
#!/usr/bin/env pwsh
# Minimal launcher - delegates to Python installer
python -m br_pre_commit.install $args
```

### Python Installer Responsibilities

The Python installer (`src/br_pre_commit/install.py`) handles:

| Responsibility | Implementation |
|----------------|----------------|
| OS detection | `platform.system()`, `sys.platform` |
| Path resolution | `pathlib.Path`, `git rev-parse` |
| Git repository discovery | `subprocess.run(["git", "rev-parse", ...])` |
| Submodule discovery | `git submodule status`, `.gitmodules` parsing |
| Hook discovery | Read `.git/hooks/pre-commit` |
| Hook creation | Generate platform-appropriate hook template |
| Hook replacement | Write hook, backup existing, set permissions |
| Hook validation | Run gap analyzer after install |
| Permissions | `os.chmod` with `stat.S_IEXEC` (POSIX) |
| Idempotency | Detect existing hook, compare, update if needed |
| Error reporting | Structured errors with remediation |
| Configuration | Read/write `.br-pre-commit.toml` |
| Gap analysis | Integrate with `GapAnalyzer` |

### Avoided Duplication

| Duplicated Logic | Old Approach | New Approach |
|------------------|--------------|--------------|
| Git repo detection | `install.sh` + `install.ps1` | Single Python function |
| Submodule path resolution | `install.sh` + `install.ps1` | Single Python function |
| Hook template generation | `install.sh` + `install.ps1` | Single Python function |
| Permission handling | `chmod` in shell | `os.chmod` in Python |
| Idempotency checks | Separate in each script | Single Python function |

### Python Installer Structure

```python
# src/br_pre_commit/install.py
"""Main installer module - all installation logic in Python."""

import argparse
import sys
from pathlib import Path
from dataclasses import dataclass

from .git_repo import GitRepo
from .submodule import SubmoduleResolver
from .hook_installer import HookInstaller
from .gap_analyzer import GapAnalyzer

@dataclass
class InstallConfig:
    repo_root: Path
    tool_root: Path
    force: bool = False
    dry_run: bool = False
    uninstall: bool = False

def main(argv: list[str] = None) -> int:
    parser = argparse.ArgumentParser(prog="br_pre_commit.install")
    parser.add_argument("repo_path", nargs="?", default=".")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_path).resolve()

    if args.verify_only:
        return verify_only(repo_root)

    if args.uninstall:
        return uninstall(repo_root)

    return install(repo_root, force=args.force, dry_run=args.dry_run)

def install(repo_root: Path, force: bool = False, dry_run: bool = False) -> int:
    # 1. Resolve tool root (submodule location)
    tool_root = SubmoduleResolver.resolve(repo_root)

    # 2. Install hook
    installer = HookInstaller(repo_root, tool_root, force=force)
    if not dry_run:
        result = installer.install()
        print(result.message)

    # 3. Verify with gap analyzer
    analyzer = GapAnalyzer(repo_root, tool_root)
    results = analyzer.run_all_checks()
    print(analyzer.format_report())

    if analyzer.has_errors():
        return 1
    return 0

def verify_only(repo_root: Path) -> int:
    tool_root = SubmoduleResolver.resolve(repo_root)
    analyzer = GapAnalyzer(repo_root, tool_root)
    results = analyzer.run_all_checks()
    print(analyzer.format_report())
    return 1 if analyzer.has_errors() else 0

def uninstall(repo_root: Path) -> int:
    tool_root = SubmoduleResolver.resolve(repo_root)
    installer = HookInstaller(repo_root, tool_root)
    if installer.uninstall():
        print("Hook uninstalled, backup restored")
        return 0
    else:
        print("No hook to uninstall")
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

### Supporting Modules

```
src/br_pre_commit/
├── install.py              # Main entry point
├── git_repo.py             # Git repository operations
├── submodule.py            # Submodule resolution
├── hook_installer.py       # Hook creation/installation
├── gap_analyzer.py         # Installation verification
├── precommit_wrapper.py    # Runtime hook entry point
└── ...
```

### Benefits

1. **Single source of truth** — All logic in Python, tested once
2. **Easier testing** — Unit test installer logic without shell
3. **Cross-platform consistency** — Same code runs everywhere
4. **Better error handling** — Python exceptions vs shell exit codes
5. **Easier maintenance** — One codebase to update
6. **Type safety** — Type hints, dataclasses, mypy checking

## Verification Checklist

- [ ] `install.sh` is minimal launcher (≤ 5 lines)
- [ ] `install.ps1` is minimal launcher (≤ 5 lines)
- [ ] All installation logic in `src/br_pre_commit/install.py`
- [ ] OS detection in Python
- [ ] Path resolution in Python
- [ ] Git operations in Python (`subprocess`)
- [ ] Submodule resolution in Python
- [ ] Hook generation in Python
- [ ] Hook installation in Python
- [ ] Permissions handled in Python
- [ ] Idempotency in Python
- [ ] Error reporting in Python
- [ ] Gap analyzer integrated
- [ ] `--force`, `--dry-run`, `--uninstall`, `--verify-only` flags work
- [ ] Unit tests for all installer components
