# 07 — Hook Registration Design

## Overview

The installer must correctly register the active Git hook. The analyzer must detect old installations and verify the current hook executes `precommit_wrapper.py` through the intended Python environment.

## Requirements

### Hook Registration

The installer must:
1. Create or update `.git/hooks/pre-commit`
2. Make it executable on POSIX (`chmod +x`)
3. On Windows, create a PowerShell-compatible hook
4. Record installation metadata in the hook (for detection/analysis)
5. Preserve existing user hook content when possible

### Old Installation Detection

The analyzer must detect these legacy patterns:

| Pattern | Example | Action |
|---------|---------|--------|
| Hook → `./run` | `exec ./run "$@"` | Migrate to direct Python |
| Hook → `./run.ps1` | `./run.ps1 $args` | Migrate to direct Python |
| Hook → absolute path | `/home/user/project/br_pre_commit/run` | Migrate to dynamic resolution |
| Hook → conda activate | `source ~/miniconda3/etc/profile.d/conda.sh` | Remove activation |

### Hook Content Verification

The installed hook must:
- Execute `python -m br_pre_commit.precommit_wrapper`
- Use the active Python (via shebang or `python` in PATH)
- Contain no hardcoded paths
- Contain installation metadata for analysis

### Hook Templates

**POSIX (Linux/WSL):**
```bash
#!/usr/bin/env sh
# br_pre_commit hook
# installed: 2026-09-15T10:30:00Z
# mode: dual
# tool_root: dynamic
# python: active
exec python -m br_pre_commit.precommit_wrapper "$@"
```

**Windows (PowerShell):**
```powershell
#!/usr/bin/env pwsh
# br_pre_commit hook
# installed: 2026-09-15T10:30:00Z
# mode: dual
# tool_root: dynamic
# python: active
python -m br_pre_commit.precommit_wrapper $args
```

### Installation Metadata

The hook header contains structured comments for the gap analyzer:

```bash
# br_pre_commit hook
# installed: <ISO8601 timestamp>
# mode: <dual|linux|windows>
# tool_root: <dynamic|absolute-path>
# python: <active|explicit-path>
# version: <installer-version>
```

### Migration from Old Hooks

**Detection logic:**
```python
def classify_hook(hook_path: Path) -> HookType:
    content = hook_path.read_text()

    if "br_pre_commit.precommit_wrapper" in content:
        return HookType.CURRENT
    elif "./run" in content or "run.ps1" in content:
        return HookType.LEGACY_SHIM
    elif "conda activate" in content or "source.*conda" in content:
        return HookType.LEGACY_CONDA
    elif "br_pre_commit" in content:
        return HookType.LEGACY_DIRECT
    else:
        return HookType.UNKNOWN
```

**Migration strategy:**
1. Backup existing hook to `.git/hooks/pre-commit.orig` (if not already backed up)
2. Write new hook with current template
3. Report what was changed

### Hook Composition (Future)

For coexisting with other hooks (see `install-detect-pre-commit-active.md`):
- Wrap existing hook: run original first, then `br_pre_commit`
- Or: install as separate hook file and chain via a wrapper

## Design: `HookInstaller` Class

```python
# src/br_pre_commit/hook_installer.py
from pathlib import Path
from enum import Enum
import stat
import subprocess
import sys
from datetime import datetime

class HookType(Enum):
    CURRENT = "current"
    LEGACY_SHIM = "legacy_shim"
    LEGACY_CONDA = "legacy_conda"
    LEGACY_DIRECT = "legacy_direct"
    UNKNOWN = "unknown"
    NONE = "none"

class HookInstaller:
    def __init__(self, repo_root: Path, tool_root: Path, force: bool = False):
        self.repo_root = repo_root
        self.tool_root = tool_root
        self.force = force
        self.hook_path = repo_root / ".git" / "hooks" / "pre-commit"

    def install(self) -> InstallResult:
        # 1. Detect existing hook
        existing_type = self._detect_existing_hook()

        # 2. Handle based on type
        if existing_type == HookType.CURRENT and not self.force:
            return InstallResult.UNCHANGED("Hook already up to date")

        if existing_type in (HookType.LEGACY_SHIM, HookType.LEGACY_CONDA,
                              HookType.LEGACY_DIRECT, HookType.UNKNOWN):
            # Backup if not already backed up
            self._backup_existing_hook()

        # 3. Generate new hook content
        hook_content = self._generate_hook()

        # 4. Write hook
        self.hook_path.write_text(hook_content)

        # 5. Make executable (POSIX)
        if sys.platform != "win32":
            self.hook_path.chmod(self.hook_path.stat().st_mode | stat.S_IEXEC)

        return InstallResult.UPDATED("Hook installed/updated")

    def _detect_existing_hook(self) -> HookType:
        if not self.hook_path.exists():
            return HookType.NONE

        content = self.hook_path.read_text()
        if "br_pre_commit.precommit_wrapper" in content:
            return HookType.CURRENT
        elif "./run" in content or "run.ps1" in content:
            return HookType.LEGACY_SHIM
        elif "conda activate" in content or "source.*conda" in content:
            return HookType.LEGACY_CONDA
        elif "br_pre_commit" in content:
            return HookType.LEGACY_DIRECT
        return HookType.UNKNOWN

    def _backup_existing_hook(self):
        backup_path = self.hook_path.with_suffix(".orig")
        if not backup_path.exists():
            import shutil
            shutil.copy2(self.hook_path, backup_path)

    def _generate_hook(self) -> str:
        is_windows = sys.platform == "win32"
        timestamp = datetime.utcnow().isoformat() + "Z"

        if is_windows:
            return f"""#!/usr/bin/env pwsh
# br_pre_commit hook
# installed: {timestamp}
# mode: dual
# tool_root: dynamic
# python: active
# version: 1.0.0
python -m br_pre_commit.precommit_wrapper $args
"""
        else:
            return f"""#!/usr/bin/env sh
# br_pre_commit hook
# installed: {timestamp}
# mode: dual
# tool_root: dynamic
# python: active
# version: 1.0.0
exec python -m br_pre_commit.precommit_wrapper "$@"
"""

    def uninstall(self) -> bool:
        """Remove the hook, restore backup if exists."""
        backup_path = self.hook_path.with_suffix(".orig")
        if backup_path.exists():
            import shutil
            shutil.move(backup_path, self.hook_path)
            return True
        elif self.hook_path.exists():
            self.hook_path.unlink()
            return True
        return False
```

## Verification Checklist

- [ ] Creates POSIX hook with shebang `#!/usr/bin/env sh`
- [ ] Creates Windows hook with shebang `#!/usr/bin/env pwsh`
- [ ] Hook executes `python -m br_pre_commit.precommit_wrapper`
- [ ] Hook is executable on POSIX
- [ ] Installation metadata in hook header
- [ ] Detects legacy `./run` shim
- [ ] Detects legacy `./run.ps1` shim
- [ ] Detects legacy conda activation
- [ ] Detects legacy absolute paths
- [ ] Backs up existing hook before overwrite
- [ ] `--force` re-installs even if current
- [ ] `uninstall()` restores backup or removes hook
- [ ] Gap analyzer verifies hook content
