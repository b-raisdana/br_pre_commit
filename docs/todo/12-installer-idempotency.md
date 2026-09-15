# 12 — Installer Idempotency Design

## Overview

Running the installer repeatedly must be safe. Multiple invocations must result in exactly one valid hook.

## Requirements

### Idempotency Guarantees

| Invocation | Behavior |
|------------|----------|
| `install` | Installs hook if missing, updates if outdated |
| `install` → `install` | No-op (reports "already up to date") |
| `install` → `install` → `install` | No-op |
| `install --force` | Always reinstalls hook |
| `install --dry-run` | Reports what would change, makes no changes |

### Specific Requirements

- **Do not duplicate hook content** — Never append to existing hook
- **Do not corrupt existing hook** — Atomic write, backup first
- **Detect expected hook** — Compare content/hash with current template
- **Update when appropriate** — Template changed, paths changed, version changed
- **Preserve unrelated user hook functionality** — Backup before overwrite
- **Detect conflicting existing hooks** — Non-br_pre_commit hooks
- **Safe migration from old `run`/`run.ps1` design** — Auto-detect and migrate
- **Clear reporting** — What changed, what didn't, why
- **Support uninstall/removal** — `install --uninstall` restores backup

## Design: Idempotent Hook Installation

### Hook Comparison Strategy

```python
# In hook_installer.py
import hashlib
from pathlib import Path

class HookInstaller:
    def __init__(self, repo_root: Path, tool_root: Path, force: bool = False):
        self.repo_root = repo_root
        self.tool_root = tool_root
        self.force = force
        self.hook_path = repo_root / ".git" / "hooks" / "pre-commit"

    def _compute_hook_hash(self, content: str) -> str:
        """Compute stable hash of hook content (ignoring timestamp)."""
        # Normalize: remove timestamp line for comparison
        lines = content.splitlines()
        normalized = [l for l in lines if not l.startswith("# installed:")]
        return hashlib.sha256("\n".join(normalized).encode()).hexdigest()[:16]

    def _generate_hook_content(self) -> str:
        """Generate the current expected hook content."""
        # ... template generation with current timestamp ...
        return hook_content

    def _get_expected_hash(self) -> str:
        return self._compute_hook_hash(self._generate_hook_content())

    def _get_current_hash(self) -> Optional[str]:
        if not self.hook_path.exists():
            return None
        content = self.hook_path.read_text()
        return self._compute_hook_hash(content)

    def is_up_to_date(self) -> bool:
        """Check if hook matches current expected content."""
        current = self._get_current_hash()
        expected = self._get_expected_hash()
        return current == expected
```

### Installation Logic

```python
from enum import Enum
from dataclasses import dataclass

class InstallAction(Enum):
    INSTALLED = "installed"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    BACKED_UP_AND_REPLACED = "backed_up_and_replaced"
    CONFLICT_DETECTED = "conflict_detected"

@dataclass
class InstallResult:
    action: InstallAction
    message: str
    backup_path: Optional[Path] = None

def install(self) -> InstallResult:
    # 1. Check if already up to date
    if not self.force and self.is_up_to_date():
        return InstallResult(
            InstallAction.UNCHANGED,
            "Hook already up to date"
        )

    # 2. Detect existing hook type
    existing_type = self._detect_existing_hook()

    # 3. Handle conflicts
    if existing_type == HookType.UNKNOWN:
        # User has a custom hook - backup and warn
        backup = self._backup_existing_hook()
        return InstallResult(
            InstallAction.CONFLICT_DETECTED,
            f"Existing non-br_pre_commit hook backed up to {backup}",
            backup
        )

    # 4. Backup if legacy or different
    backup = None
    if existing_type in (HookType.LEGACY_SHIM, HookType.LEGACY_CONDA,
                         HookType.LEGACY_DIRECT):
        backup = self._backup_existing_hook()

    # 5. Write new hook
    self._write_hook()

    # 6. Determine action
    if existing_type == HookType.NONE:
        action = InstallAction.INSTALLED
        msg = "Hook installed"
    elif existing_type == HookType.CURRENT:
        action = InstallAction.UPDATED
        msg = "Hook updated"
    else:
        action = InstallAction.BACKED_UP_AND_REPLACED
        msg = f"Legacy hook replaced (backup: {backup})"

    return InstallResult(action, msg, backup)
```

### Backup Strategy

```python
def _backup_existing_hook(self) -> Path:
    """Backup existing hook to .orig if not already backed up."""
    backup_path = self.hook_path.with_suffix(".orig")

    if backup_path.exists():
        # Already backed up - don't overwrite
        return backup_path

    import shutil
    shutil.copy2(self.hook_path, backup_path)
    return backup_path
```

### Uninstall

```python
def uninstall(self) -> bool:
    """Remove hook, restore backup if exists."""
    backup_path = self.hook_path.with_suffix(".orig")

    if backup_path.exists():
        # Restore backup
        import shutil
        shutil.move(backup_path, self.hook_path)
        print(f"Restored backup from {backup_path}")
        return True
    elif self.hook_path.exists():
        # No backup - just remove
        self.hook_path.unlink()
        print("Removed hook (no backup found)")
        return True
    else:
        print("No hook to uninstall")
        return False
```

### Dry Run

```python
def dry_run(self) -> InstallResult:
    """Simulate installation without making changes."""
    if self.is_up_to_date():
        return InstallResult(InstallAction.UNCHANGED, "Hook already up to date")

    existing_type = self._detect_existing_hook()

    if existing_type == HookType.NONE:
        return InstallResult(InstallAction.INSTALLED, "Would install new hook")
    elif existing_type == HookType.CURRENT:
        return InstallResult(InstallAction.UPDATED, "Would update hook (template changed)")
    elif existing_type in (HookType.LEGACY_SHIM, HookType.LEGACY_CONDA, HookType.LEGACY_DIRECT):
        return InstallResult(InstallAction.BACKED_UP_AND_REPLACED,
                            "Would backup legacy hook and install new one")
    else:
        return InstallResult(InstallAction.CONFLICT_DETECTED,
                            "Would backup unknown hook and install new one")
```

### Reporting

```
$ python -m br_pre_commit.install
Hook already up to date

$ python -m br_pre_commit.install --force
Hook updated (forced reinstall)

$ python -m br_pre_commit.install --dry-run
Would update hook (template changed)

$ python -m br_pre_commit.install  # First time on legacy
Legacy hook backed up to .git/hooks/pre-commit.orig
Hook installed
```

## Migration from Old Design

| Old Hook Pattern | Detection | Migration |
|------------------|-----------|-----------|
| `exec ./run "$@"` | `./run` in content | Backup → install direct hook |
| `./run.ps1 $args` | `run.ps1` in content | Backup → install direct hook |
| `source ~/miniconda3/...` | `conda activate` in content | Backup → install direct hook |
| Absolute path to tool | Tool root in content | Backup → install dynamic hook |

## Verification Checklist

- [ ] `install` → `install` reports "already up to date"
- [ ] `install --force` always reinstalls
- [ ] `install --dry-run` makes no changes
- [ ] Hook content never duplicated
- [ ] Existing hook backed up before overwrite
- [ ] Legacy `run`/`run.ps1` hooks detected and migrated
- [ ] Unknown hooks backed up (not deleted)
- [ ] `install --uninstall` restores backup
- [ ] Clear action messages for each case
- [ ] Atomic write (write to temp, then rename)
- [ ] Permissions preserved/set correctly
