# TODO: Resolve `tomllib` Python 3.9 incompatibility

## Problem

`src/br_pre_commit/precommit_config.py:3` imports the standard library `tomllib`:

```python
import tomllib
```

`tomllib` was added in **Python 3.11** (PEP 680). It does not exist in Python 3.9 and will raise `ModuleNotFoundError` at import time. This is a **hard blocker** for Python 3.9 adoption.

## Usage

`tomllib.loads()` and `tomllib.load()` are used at `precommit_config.py:17-19` for loading TOML config files (`.br-pre-commit.toml` and `defaults.toml`).

## Fix options

### Option A: `tomli` fallback (recommended)

```python
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
```

Then add `tomli; python_version < "3.11"` to project dependencies. `tomli` is the reference implementation that `tomllib` was based on and has an identical API.

**Pros**: Clean, well-established pattern. `tomli` is already used by many tools in the Python ecosystem.
**Cons**: Adds an external dependency for Python < 3.11.

### Option B: Use `tomli` unconditionally

Replace `import tomllib` with `import tomli as tomllib` everywhere, and add `tomli` to dependencies unconditionally.

**Pros**: Single dependency, no try/except.
**Cons**: Unnecessary dependency on Python 3.11+ where `tomllib` is built-in.

### Option C: Custom minimal TOML parser

Not recommended — overkill for config parsing.

## Files to change

| File | Change |
|------|--------|
| `src/br_pre_commit/precommit_config.py` | Add `tomli` fallback import |
| `pyproject.toml` | Add `tomli; python_version < "3.11"` dependency |

## Verification

1. `python3.9 -c "from br_pre_commit.precommit_config import _merged_config"` succeeds.
2. `unknown_hook_policy()`, `job_timeout_seconds()`, etc. work on Python 3.9.
3. TOML config loading produces correct results on both 3.9 (via tomli) and 3.11+ (via tomllib).
