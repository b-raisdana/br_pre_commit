# TODO: Replace `datetime.UTC` with `datetime.timezone.utc`

## Problem

`src/precommit_wrapper.py:13` imports `UTC` from `datetime`:

```python
from datetime import UTC
```

`datetime.UTC` was added in **Python 3.11** (PEP 685). It does not exist in Python 3.9 and will raise `ImportError` at module load time, making this a hard blocker for Python 3.9 adoption.

## Usage

The import is used at `src/precommit_wrapper.py:276`:

```python
timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
```

`datetime.now(UTC)` returns the current UTC-aware datetime.

## Fix

Replace the import and all usages:

```python
# Before (Python 3.11+):
from datetime import UTC
timestamp = datetime.now(UTC).strftime(...)

# After (Python 3.9+):
from datetime import timezone
timestamp = datetime.now(timezone.utc).strftime(...)
```

`datetime.timezone.utc` has existed since Python 3.2 and provides identical behavior.

## Files to change

| File | Line | Change |
|------|------|--------|
| `src/precommit_wrapper.py` | 13 | `from datetime import UTC` → `from datetime import timezone` |
| `src/precommit_wrapper.py` | 276 | `datetime.now(UTC)` → `datetime.now(timezone.utc)` |

## Verification

- Module imports without error on Python 3.9.
- `precommit_wrapper._main_async()` produces correct UTC timestamps after the change.
- Existing tests in `tests/test_precommit_wrapper.py` still pass.
