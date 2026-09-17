# Diagnosis: Unregistered pre-commit hook IDs

## Symptom

Running `./pre-commit` in a freshly cloned project that uses the
`br_pre_commit` wrapper fails immediately:

```
Running pre-commit wrapper in /home/brais/code/XAAUSD-PAction-projectFolder
Unstaged files detected.
Stashing unstaged files to /home/brais/.cache/pre-commit/patch1789186972-267100.
Restored changes from /home/brais/.cache/pre-commit/patch1789186972-267100.
configuration error: unregistered pre-commit hook(s): ruff-check, pytest
```

The wrapper then triggers a backup snapshot (because the commit "failed") and
writes a log entry — but the actual problem is a configuration error, not a
hook failure.

## Root cause

The `br_pre_commit` wrapper classifies every hook ID in your
`.pre-commit-config.yaml` against two fixed frozensets in
`src/precommit_config.py`:

- `_MUTATING_HOOKS` — run serially before read-only hooks (e.g. `ruff`,
  `ruff-format`, `trailing-whitespace`).
- `_READ_ONLY_HOOKS` — run concurrently (e.g. `pytest-fast`, `check-yaml`,
  `incremental-ratchet`).

The default `wrapper.unknown-hook-policy` is `"error"` (see `pyproject.toml`,
`[tool.br_pre_commit.wrapper]`, line 5). Any hook ID not present in either set is
"unregistered" and aborts the commit with `ValueError: unregistered pre-commit hook(s): <ids>`.

Your `chrge_migrate-to-pandas` branch's `.pre-commit-config.yaml` defines two
local hooks whose IDs are not in those sets:

| Your ID | Recognized ID | Why yours fails |
|---------|---------------|-----------------|
| `ruff-check` | `ruff` | `ruff-check` is not in `_MUTATING_HOOKS` or `_READ_ONLY_HOOKS`; the wrapper only knows `ruff`. |
| `pytest` | `pytest-fast` | `pytest` is not in either set; the wrapper only knows `pytest-fast`. |

`ruff-format` is already correct (it is in `_MUTATING_HOOKS`).

## What went wrong in the project's config

The project's `.pre-commit-config.yaml` does not match the **recognized hook
ID** contract that `br_pre_commit` enforces. Specifically:

1. **`ruff-check` is not a recognized ID.** The wrapper's `_MUTATING_HOOKS`
   set contains `ruff` (the standard `astral-sh/ruff-pre-commit` hook ID), not
   `ruff-check`. This is a common mistake — the local hook uses an `entry` that
   runs `python -m ruff check`, and the author named the hook `ruff-check`
   instead of using the canonical ID `ruff`.

2. **`pytest` is not a recognized ID.** The wrapper's `_READ_ONLY_HOOKS` set
   contains `pytest-fast`, not `pytest`. The local hook's entry
   (`python -m pytest`) is fine, but the `id` must be `pytest-fast` to be
   classified.

## How to fix it (correct the project's config)

In `.pre-commit-config.yaml`, change the `id` fields (only the `id`, not the
`entry` or `name`):

```yaml
repos:
  - repo: local
    hooks:
      - id: ruff               # was: ruff-check
        name: ruff-check
        entry: python -m ruff check
        language: system
        types: [python]
      - id: ruff-format
        name: ruff-format
        entry: python -m ruff format --check
        language: system
        types: [python]
      - id: pytest-fast        # was: pytest
        name: pytest
        entry: python -m pytest
        language: system
        pass_filenames: false
```

The `name` field is a display label and can be anything — only the `id` matters
for classification. After this change, all three hooks are recognized:

- `ruff` → `_MUTATING_HOOKS` (serial, before read-only hooks)
- `ruff-format` → `_MUTATING_HOOKS` (serial)
- `pytest-fast` → `_READ_ONLY_HOOKS` (concurrent)

## Alternative: warn-only policy (not recommended as a permanent fix)

If the project has a genuinely custom hook that does not fit the recognized
categories, set `unknown-hook-policy = "warn"` in the `[tool.br_pre_commit.wrapper]`
section of `pyproject.toml`:

```toml
[tool.br_pre_commit.wrapper]
unknown-hook-policy = "warn"
```

With `"warn"`, unknown hooks are run serially instead of blocking the commit.
This is a workaround — the README § "Recognized hook IDs" explains why it is
not a replacement for using registered IDs.

## Where to find the full list of recognized hook IDs

- **README.md** — § "Recognized hook IDs" (this is the human-readable list).
- **pyproject.toml** — `unknown-hook-policy = "error"` under
  `[tool.br_pre_commit.wrapper]` (the default policy).
- **src/precommit_config.py** — `_MUTATING_HOOKS` (lines 42–51)
  and `_READ_ONLY_HOOKS` (lines 52–67) are the source of truth.
- **.pre-commit-config.yaml** — the reference config; all its
  hook IDs pass the `test_repository_pre_commit_config_uses_registered_hooks`
  test.
- **tests/test_precommit_config.py** — `classify_hooks` is unit-tested for
  both `"error"` and `"warn"` policies.
