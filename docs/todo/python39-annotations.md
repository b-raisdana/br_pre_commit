# TODO: Handle PEP 604 union type annotations for Python 3.9

## Problem

The codebase uses PEP 604 union syntax (`X | Y`, `bytes | None`, `str | None`, etc.) extensively in type annotations across all modules:

- `dict[str, list[tuple[str, str, bytes | None]]` — `sync_skill_sync.py:24`
- `bytes | None` — `sync_skill_core.py:48`
- `str | None` — `precommit_wrapper.py:255,312`
- `X | None` — `ratchet_check.py:243,257,282`
- And many more occurrences throughout `src/**/*.py` and `tests/**/*.py`

## Why it works today (Python 3.12)

Every module uses `from __future__ import annotations` (added in Python 3.7), which stores all annotations as strings and never evaluates them at runtime. So `bytes | None` in an annotation works fine even though `bytes | None` as an *expression* would fail on Python 3.9.

There is **no** `typing.get_type_hints()` call in the codebase, so annotations are never resolved back to live types.

## The ruff complication

With `ruff target-version = "py39"` (required by this migration), ruff's `UP006` rule will flag every PEP 604 union annotation and suggest converting it to `Union[X, Y]` or `Optional[X]`. Similarly, `UP007` flags `X | None` → `Optional[X]`.

## Decision options

### Option A: Convert all PEP 604 unions to `Union`/`Optional`

Add `from typing import Union, Optional` and replace:
- `X | Y` → `Union[X, Y]`
- `X | None` → `Optional[X]`

**Pros**: Satisfies ruff UP006/UP007 cleanly; maximizes runtime `get_type_hints()` compatibility if ever needed.
**Cons**: ~50+ annotation changes across 9 files; no functional benefit given `from __future__ import annotations` is already in use.

### Option B: Keep PEP 604 syntax, configure ruff to allow it

Keep the modern syntax (valid with `from __future__ import annotations` on 3.9) and configure ruff:

```toml
[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "C4", "SIM", "W"]
# Allow PEP 604 unions (enabled by `from __future__ import annotations`)
ignore = ["UP006", "UP007"]
```

Or more precisely, enable `UP` but add the rules to `ignore`.

**Pros**: Minimal code changes; PEP 604 syntax is cleaner and more readable.
**Cons**: Ruff UP006/UP007 won't catch cases where annotations might be evaluated at runtime (defensive only).

### Recommended: Option B

The codebase already uses `from __future__ import annotations` consistently. Converting ~50 annotations to `Union`/`Optional` adds noise with no functional benefit. If future code disables the future import, UP006/UP007 would catch it then.

## Files with PEP 604 annotations (if Option A is chosen)

| File | Example patterns |
|------|-----------------|
| `src/br_pre_commit/sync_skill.py` | `list[str]`, `set[str]` |
| `src/br_pre_commit/sync_skill_sync.py` | `bytes | None`, `dict[str, ...]`, `set[str] \| None` |
| `src/br_pre_commit/recover.py` | `str \| None`, `list[...]` |
| `src/br_pre_commit/precommit_wrapper.py` | `str \| None`, `dict[str, object]`, `JobResult \| None` |
| `src/br_pre_commit/backup.py` | `dict[str, str] \| None` |
| `src/br_pre_commit/sync_skill_utils.py` | `bytes \| None`, `set[str]` |
| `src/br_pre_commit/sync_skill_core.py` | `bytes \| None`, `tuple[str, str] \| None` |
| `src/br_pre_commit/incremental_precommit/ratchet_check.py` | `int \| None`, `Path \| None` |
| `tests/**/*.py` | Various union types |

## Verification

1. `ruff check --target-version py39` reports no UP006/UP007 violations (or reports them but they're intentionally ignored per Option B).
2. Module imports succeed on Python 3.9.
3. Tests pass on Python 3.9.
