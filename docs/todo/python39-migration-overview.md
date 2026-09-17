# TODO: Adopt entire project to Python 3.9

## Goal

Lower the project's Python version target from 3.12 to 3.9 so the codebase runs on any Python 3.9+ interpreter. This enables use on systems and CI images that only provide Python 3.9.

## Scope

All source code, tests, and tooling configuration under `src/`, `tests/`, `pyproject.toml`, and `.pre-commit-config.yaml`.

## Current state

The project currently targets Python 3.12 (ruff `target-version = "py312"`). It uses features that are unavailable or behave differently in Python 3.9:

| Issue | File(s) | Severity |
|-------|---------|----------|
| `from datetime import UTC` (3.11+) | `src/precommit_wrapper.py:13` | Hard blocker |
| `import tomllib` (3.11+) | `src/precommit_config.py:3` | Hard blocker |
| PEP 604 union syntax `X \| Y` in annotations | All `src/**/*.py`, `tests/**/*.py` | Ruff flag (soft) |
| `ruff target-version = "py312"` | `pyproject.toml:6` | Config |
| No `python_requires` declared | `pyproject.toml` | Config |

## Migration plan

| Step | Doc | Priority |
|------|-----|----------|
| Overview | This file | — |
| Fix `datetime.UTC` → `timezone.utc` | `docs/todo/python39-datetime-utc.md` | High |
| Resolve `tomllib` → `tomli` fallback | `docs/todo/python39-tomllib.md` | High |
| Handle PEP 604 union annotations | `docs/todo/python39-annotations.md` | High |
| Update tooling config (ruff, pyproject) | `docs/todo/python39-tooling.md` | High |
| Verify (lint, typecheck, tests) | `docs/todo/python39-verification.md` | High |

## Compatibility rules for this migration

- **Runtime evaluation**: All modules use `from __future__ import annotations`, so annotations are stored as strings and never evaluated at runtime. This means PEP 585 generics (`dict[str, int]`) and PEP 604 unions (`X | Y`) in *annotation position* are safe at runtime on Python 3.9 without conversion — unless a tool calls `typing.get_type_hints()`.
- **No `typing.get_type_hints()` usage** exists in the codebase, so the `future` import fully defers evaluation.
- **Third-party runtime introspection** (IDEs, mypy, pyright) understands PEP 604 syntax with the future import, so no conversion is strictly required for correctness.
- **Ruff UP006/UP007** will flag PEP 604 syntax when `target-version = "py39"`. The decision (convert vs. disable) is documented in `docs/todo/python39-annotations.md`.
- **`tomllib`** (Python 3.11+ stdlib) is imported in `precommit_config.py`. Requires a `tomli` fallback — see `docs/todo/python39-tomllib.md`.
- **Built-in `Path.unlink(missing_ok=True)`**: available since Python 3.8, no change needed.
- **`threading.Barrier`**: available since Python 3.5, no change needed (used in `tests/test_ratchet_check.py:67`).

## Files that need changes

| File | Change |
|------|--------|
| `src/precommit_wrapper.py` | Replace `from datetime import UTC` with `from datetime import timezone` |
| `src/precommit_config.py` | Add `tomli` fallback for `tomllib` |
| `pyproject.toml` | `target-version = "py39"`, add `python_requires` |
| `src/**/*.py`, `tests/**/*.py` | Optional: convert PEP 604 unions (see annotations doc) |

## Verification

1. `ruff check` passes with `target-version = "py39"` (no UP006/UP007 violations or suppressed intentionally).
2. `ruff format` passes.
3. `pytest -m unit` passes on Python 3.9.
4. `mypy` passes (if configured) on Python 3.9.
5. All pre-commit hooks in `.pre-commit-config.yaml` run successfully.
6. `from br_pre_commit.precommit_config import _merged_config` succeeds on Python 3.9 (tomli fallback works).
