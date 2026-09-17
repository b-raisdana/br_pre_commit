# 06 — Gap Analyzer Design

## Overview

An analyzer that verifies the installation and current integration. It checks a comprehensive list of items and reports OK/WARNING/ERROR with remediation commands.

## Requirements

### Checks to Perform

| Check | Description | Severity if Failed |
|-------|-------------|-------------------|
| Git repository detected | `.git` exists and is valid | ERROR |
| br_pre_commit submodule detected | Submodule registered and path resolves | ERROR |
| requirements.txt detected | File exists at tool root | ERROR |
| precommit_wrapper.py detected | Entry point exists | ERROR |
| pre-commit hook detected | `.git/hooks/pre-commit` exists | ERROR |
| Hook points to expected implementation | Hook content matches current design | ERROR |
| Hook is executable (POSIX) | `os.access(hook, os.X_OK)` | ERROR (POSIX) |
| Active Python detected | `sys.executable` valid | ERROR |
| Python version supported | ≥ 3.9 | ERROR |
| Required packages installed | All packages from requirements.txt importable | ERROR |
| Required packages importable | Same as above (redundant check) | ERROR |
| Obsolete hook calls run | `.git/hooks/pre-commit` → `exec ./run` | WARNING |
| Obsolete hook calls run.ps1 | `.git/hooks/pre-commit` → `./run.ps1` | WARNING |
| Stale hook detected | Hook points to old/moved location | WARNING |
| Duplicate hook registration detected | Multiple hook mechanisms active | WARNING |

### Report Format

```
╔══════════════════════════════════════════════════════════════════╗
║                    br_pre_commit Gap Analysis                    ║
╠══════════════════════════════════════════════════════════════════╣
║ Repository: /home/user/my-project                                 ║
║ Tool root:  /home/user/my-project/br_pre_commit                  ║
║ Python:     /home/user/.venv/bin/python (3.12.3)                 ║
╠══════════════════════════════════════════════════════════════════╣
║ ✓ OK        Git repository detected                              ║
║ ✓ OK        br_pre_commit submodule detected                     ║
║ ✓ OK        requirements.txt detected                            ║
║ ✓ OK        precommit_wrapper.py detected                        ║
║ ✓ OK        pre-commit hook detected                             ║
║ ✓ OK        Hook points to expected implementation               ║
║ ✓ OK        Hook is executable                                   ║
║ ✓ OK        Active Python detected                               ║
║ ✓ OK        Python version supported (3.12.3 ≥ 3.9)              ║
║ ✓ OK        Required packages installed                          ║
║ ✓ OK        Required packages importable                         ║
║ ⚠ WARNING   Obsolete run shim detected in hook                   ║
║    → Fix:   python -m br_pre_commit.install --force              ║
║ ⚠ WARNING   Stale hook detected (tool path mismatch)             ║
║    → Fix:   python -m br_pre_commit.install                      ║
╚══════════════════════════════════════════════════════════════════╝

Summary: 12 OK, 2 WARNING, 0 ERROR
```

### Remediation Commands

Each WARNING/ERROR should provide a practical fix command:

| Issue | Remediation |
|-------|-------------|
| Obsolete hook shim | `python -m br_pre_commit.install --force` |
| Obsolete run ps1 shim | `python -m br_pre_commit.install --force` |
| Stale hook (path mismatch) | `python -m br_pre_commit.install` |
| Duplicate hook | `python -m br_pre_commit.install --clean` |
| Missing packages | `python -m pip install -r "/abs/path/to/requirements.txt"` |
| Python version too old | `Use Python ≥ 3.9 (current: X.Y.Z)` |
| Hook not executable | `chmod +x .git/hooks/pre-commit` |

## Design: `GapAnalyzer` Class

```python
# src/gap_analyzer.py
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional
import sys
import os
import subprocess

class Severity(Enum):
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"

@dataclass
class CheckResult:
    name: str
    severity: Severity
    message: str
    remediation: Optional[str] = None
    details: Optional[str] = None

class GapAnalyzer:
    def __init__(self, repo_root: Path, tool_root: Path):
        self.repo_root = repo_root
        self.tool_root = tool_root
        self.results: List[CheckResult] = []

    def run_all_checks(self) -> List[CheckResult]:
        self.results = []

        # Core existence checks
        self._check_git_repo()
        self._check_submodule()
        self._check_requirements_txt()
        self._check_precommit_wrapper()
        self._check_hook_exists()
        self._check_hook_content()
        self._check_hook_executable()

        # Python environment checks
        self._check_python_version()
        self._check_dependencies()

        # Legacy/staleness checks
        self._check_obsolete_shims()
        self._check_stale_hook()
        self._check_duplicate_hooks()

        return self.results

    def _check_git_repo(self):
        git_dir = self.repo_root / ".git"
        if git_dir.exists():
            self._ok("Git repository detected")
        else:
            self._error("Git repository not found", "Run inside a Git repository")

    def _check_submodule(self):
        # Use git submodule status or .gitmodules parsing
        result = subprocess.run(
            ["git", "submodule", "status", "br_pre_commit"],
            cwd=self.repo_root, capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            self._ok("br_pre_commit submodule detected")
        else:
            self._error(
                "br_pre_commit submodule not found",
                "git submodule add <url> br_pre_commit"
            )

    def _check_hook_content(self):
        hook_path = self.repo_root / ".git" / "hooks" / "pre-commit"
        if not hook_path.exists():
            return

        content = hook_path.read_text()
        expected_marker = "br_pre_commit.precommit_wrapper"

        if expected_marker in content:
            self._ok("Hook points to expected implementation")
        # Check for hooks that call run/run.ps1 as legacy shims
        if "exec ./run" in content or 'exec "./run"' in content:
            self._warning(
                "Obsolete run shim detected in hook",
                'python -m br_pre_commit.install --force'
            )
        elif "./run.ps1" in content or ".\\run.ps1" in content:
            self._warning(
                "Obsolete run.ps1 shim detected in hook",
                'python -m br_pre_commit.install --force'
            )
        else:
            self._warning(
                "Hook points to unknown implementation",
                'python -m br_pre_commit.install --force'
            )

    def _check_obsolete_shims(self):
        # Check for obsolete run/run.ps1 hook scripts that no longer exist.
        # The run and run.ps1 launcher scripts in the repo root are valid
        # and should NOT be flagged.
        for shim in ["run", "run.ps1"]:
            shim_path = self.tool_root / shim
            # Only flag if they exist in .git/hooks as leftover hook files
            hook_shim = self.repo_root / ".git" / "hooks" / shim
            if hook_shim.exists():
                self._warning(
                    f"Obsolete {shim} hook file in .git/hooks",
                    f"Remove {hook_shim} or reinstall hook"
                )

    def _check_stale_hook(self):
        hook_path = self.repo_root / ".git" / "hooks" / "pre-commit"
        if not hook_path.exists():
            return

        content = hook_path.read_text()
        # Check for absolute paths that might be stale
        if str(self.tool_root) in content:
            # Hook has hardcoded tool path — check if it matches current
            current_tool_root = self.tool_root.resolve()
            if str(current_tool_root) not in content:
                self._warning(
                    "Stale hook detected (tool path mismatch)",
                    'python -m br_pre_commit.install'
                )

    def _ok(self, msg: str):
        self.results.append(CheckResult(msg, Severity.OK, msg))

    def _warning(self, msg: str, remediation: str):
        self.results.append(CheckResult(msg, Severity.WARNING, msg, remediation))

    def _error(self, msg: str, remediation: str):
        self.results.append(CheckResult(msg, Severity.ERROR, msg, remediation))

    def format_report(self) -> str:
        # Format as shown in the table above
        ...

    def has_errors(self) -> bool:
        return any(r.severity == Severity.ERROR for r in self.results)

    def has_warnings(self) -> bool:
        return any(r.severity == Severity.WARNING for r in self.results)

def main():
    """CLI entry point: python -m br_pre_commit.gap_analyzer"""
    repo_root = Path(subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True
    ).strip())

    # Resolve tool root (submodule or package)
    tool_root = resolve_tool_root(repo_root)

    analyzer = GapAnalyzer(repo_root, tool_root)
    results = analyzer.run_all_checks()

    print(analyzer.format_report())

    if analyzer.has_errors():
        sys.exit(1)
    elif analyzer.has_warnings():
        sys.exit(0)  # Warnings don't fail by default
    else:
        sys.exit(0)
```

## Integration Points

### Installer Integration

After installation, run the gap analyzer automatically:

```python
# In installer.py
def install(...):
    # ... perform installation ...

    # Verify
    analyzer = GapAnalyzer(repo_root, tool_root)
    results = analyzer.run_all_checks()

    if analyzer.has_errors():
        print("Installation completed with ERRORS:")
        print(analyzer.format_report())
        sys.exit(1)
    elif analyzer.has_warnings():
        print("Installation completed with WARNINGS:")
        print(analyzer.format_report())
    else:
        print("Installation verified successfully.")
```

### Standalone Command

```bash
# Run anytime to diagnose
python -m br_pre_commit.gap_analyzer
```

## Verification Checklist

- [ ] All 15 checks implemented
- [ ] OK/WARNING/ERROR formatting correct
- [ ] Remediation commands are copy/pasteable
- [ ] Absolute paths in remediation commands
- [ ] `python -m pip` used in remediation
- [ ] Runs as standalone command
- [ ] Runs automatically after install
- [ ] Detects legacy `./run`/`./run.ps1` hooks (not the launcher scripts)
- [ ] Detects stale hook paths
- [ ] Detects duplicate hook registration
- [ ] Exit code: 0 for OK/WARNING, 1 for ERROR
