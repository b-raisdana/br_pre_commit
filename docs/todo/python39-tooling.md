# TODO: Update tooling configuration for Python 3.9 target

## Problem

Several tool configurations currently target Python 3.12, which both causes false-positive lint flags and misrepresents the project's compatibility.

## Changes

### 1. `pyproject.toml` — ruff target-version

**File**: `pyproject.toml:6`

```toml
# Before:
[tool.ruff]
target-version = "py312"

# After:
[tool.ruff]
target-version = "py39"
```

This changes ruff's interpretation of which Python features are available. Notably:
- `UP006` (PEP 604 unions) and `UP007` (`X | None` → `Optional[X]`) will start flagging annotations. See `docs/todo/python39-annotations.md` for the resolution strategy.
- `UP004` (redundant `typing` imports) may flag `typing` imports that are unnecessary on 3.9 with PEP 585.
- PEP 585 generic builtins (`dict[str, int]`, `list[str]`, etc.) are allowed (they were added in 3.9).

### 2. `pyproject.toml` — add `python_requires`

Add to `[project]` section (or create one if absent):

```toml
[project]
requires-python = ">=3.9"
```

Note: If `[project]` section doesn't exist in `pyproject.toml`, check whether the project uses a different packaging approach (e.g., setuptools config, poetry, etc.). The current `pyproject.toml` only has `[tool.pytest.ini_options]` and `[tool.ruff]`, so a `[project]` section may need to be added or the `python_requires` may need to go in the appropriate build-system section.

### 3. `pyproject.toml` — Python classifier (optional)

If using setuptools or similar, add:

```toml
[project]
classifiers = [
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3 :: Only",
]
```

### 4. `.pre-commit-config.yaml` — hook version compatibility

Verify that all pre-commit hook versions support Python 3.9:
- `pre-commit/pre-commit-hooks` rev `v5.0.0` — verify 3.9 support.
- `astral-sh/ruff-pre-commit` rev `v0.16.2` — verify 3.9 support.

### 5. `ruff` rule behavior changes on py39 target

When changing `target-version` from `py312` to `py39`, review any newly enabled/flagged rules:
- `UP006`/`UP007`: PEP 604 union syntax (see annotations doc)
- `UP004`: Unnecessary `typing` imports (PEP 585 makes some redundant on 3.9)
- `UP013`: `typing.TypeAlias` (may be flagged if used — but not used in this codebase)
- `UP034`: `random.randrange()` → `random.randint()` — check if applicable
- `UP036`: ` collections.abc` imports — verify no changes needed

## Files to change

| File | Change |
|------|--------|
| `pyproject.toml` | `target-version = "py39"`, add `requires-python` |
| `.pre-commit-config.yaml` | Verify hook rev versions (if needed) |
| `src/**/*.py`, `tests/**/*.py` | Per annotations doc decision |

## Verification

1. `ruff check --target-version py39` — no unexpected flags.
2. `ruff format --check` — passes.
3. `python3.9 -m pytest -m unit` — all tests pass.
4. Pre-commit hooks run successfully on a Python 3.9 interpreter.
