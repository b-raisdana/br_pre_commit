# TODO: Verify Python 3.9 compatibility end-to-end

## Goal

Confirm that after all migration changes, the project runs correctly on Python 3.9.

## Prerequisites

- A Python 3.9 interpreter available (e.g., `python3.9` or via `conda`/`pyenv`).
- All project dependencies installable on Python 3.9.

## Verification steps

### 1. Install dependencies on Python 3.9

```bash
python3.9 -m pip install -e .
python3.9 -m pip install pre-commit pyyaml
```

Verify `gitpython` (used by `sync_skill_core.py`, `sync_skill_sync.py`, etc.) supports 3.9.

### 2. Lint with Python 3.9 target

```bash
ruff check --target-version py39 src/ tests/
ruff format --check src/ tests/
```

Expected: Clean, or only intentionally-suppressed UP006/UP007 violations per `docs/todo/python39-annotations.md`.

### 3. Run unit tests

```bash
python3.9 -m pytest -m unit
```

All tests in `tests/` must pass. Key test files:
- `tests/test_precommit_config.py`
- `tests/test_sync_skill_files.py`
- `tests/test_precommit_wrapper.py`
- `tests/test_recover.py`
- `tests/test_ratchet_check.py`
- `tests/test_backup.py`

### 4. Run integration / end-to-end checks

- Execute `src/br_pre_commit/sync_skill.py` as a script in a test repo.
- Execute `src/br_pre_commit/precommit_wrapper.py` on a repo with staged changes.
- Execute `src/br_pre_commit/backup.py` and `src/br_pre_commit/recover.py` round-trip.
- Execute `src/br_pre_commit/incremental_precommit/ratchet_check.py` against a real commit.

### 5. Pre-commit hook validation

Install the project's `.pre-commit-config.yaml` on a Python 3.9 environment and run `pre-commit run --all-files`. Verify all hooks complete successfully.

### 6. Cross-version check (optional)

If the project still wants to support Python 3.12, verify that changes made for 3.9 compatibility don't break 3.12:

```bash
python3.12 -m pytest -m unit
```

## Known risk areas

| Area | Risk | Mitigation |
|------|------|------------|
| `datetime.timezone.utc` behavior | Low — identical to `datetime.UTC` on 3.11+ | Test timestamp generation |
| PEP 604 annotations with future import | Low — tested by existing test suite | Full test run |
| `tomllib` compatibility | **High** — hard import blocker, separate doc | See `docs/todo/python39-tomllib.md` |
| `pathlib.Path.unlink(missing_ok=True)` | Low — available since 3.8 | Already tested |

### Critical blocker: `tomllib`

`src/br_pre_commit/precommit_config.py` imports `tomllib` which **does not exist** in Python 3.9. This is the most fundamental blocker — the module cannot be imported at all without a fallback. See dedicated doc `docs/todo/python39-tomllib.md` for the fix strategy (likely `tomli` fallback with `try/except ModuleNotFoundError`).

## Sign-off checklist

- [ ] `datetime.UTC` replaced with `timezone.utc`
- [ ] Ruff target-version set to py39
- [ ] PEP 604 annotations handled (convert or suppress)
- [ ] `tomllib` compatibility resolved (separate todo)
- [ ] `python_requires` set in pyproject.toml
- [ ] All unit tests pass on Python 3.9
- [ ] All pre-commit hooks pass on Python 3.9
- [ ] Cross-version check passes on Python 3.12 (if applicable)
