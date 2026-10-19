# Agent Guide

This is the shared project guide for Codex, Claude, Kilo, Copilot, Devin, and
other coding agents. Read this file first; follow links only for the subsystem
or workflow being changed. Keep platform-specific setup as a short pointer here,
not a second copy of these rules.

## Start here

- Read the root `README.md` for the public configuration and integration contract.
- Read `src/README.md` for the runtime package map; each subsystem README documents its local behavior and invariants.
- Read `tests/README.md` before changing tests. Tests mirror the source packages under `tests/unit/`, `tests/integration/`, and `tests/e2e/`.
- Check `git status --short` and inspect the relevant diff before editing. Preserve existing staged, unstaged, and untracked work; do not revert or reformat unrelated changes.

## Find the owning code

| Concern | Entry point |
| --- | --- |
| Hook scheduling, classification, reports | `src/precommit_wrapper/` |
| Git snapshots and recovery | `src/backup/` |
| Incremental quality gate and baselines | `src/ratchet/` |
| Mirrored agent skill files | `src/sync_skills/` |
| Shared config, git, paths | `src/helper/` |
| Hook installation | `src/install.py`, `src/INSTALL.md` |
| Hook policy and defaults | `.pre-commit-config.yaml`, `pyproject.toml` |

Prefer the smallest change at the owning layer. Configuration and public hook IDs are documented in the root README; keep those docs aligned when changing their contract. `SKILL.md` files are mirrored across agent directories by `sync-skill-files`; edit one canonical staged copy and let the hook synchronize it.

## Fast commands

Run from the repository root:

```sh
# Fast isolated gate used by the pre-commit hook
python -m pytest -q -m unit

# One focused test module or test case
python -m pytest -q tests/unit/<area>/test_<module>.py
python -m pytest -q tests/unit/<area>/test_<module>.py::test_<name>

# Full suite, including integration and end-to-end tests
python -m pytest -q

# Static checks
ruff check src tests
ruff format --check src tests
mypy src tests
```

Use the narrowest relevant test first, then the unit gate for Python changes. Run the full suite when changes cross subsystem boundaries or affect integration behavior. Do not run mutating checks such as `ruff check --fix` unless the intended files are in scope.

The repository hook is installed with `bash install.sh "$PWD"`; it invokes the configured pre-commit pipeline. Its protected-branch guard rejects direct commits on `main`, `develop`, and `uat`, so do not interpret that guard as a code check failure.

The wrapper runs file-mutating hooks serially before launching read-only and advisory jobs concurrently. Do not parallelize mutating hooks: each pre-commit `staged_files_only` sandbox uses Git checkout and patch restoration against the shared worktree, so overlapping sandboxes can overwrite staged or unstaged changes. See `src/precommit_wrapper/README.md` for the scheduling details.

## Change discipline

- Preserve behavior unless the request explicitly authorizes a behavior change. Trace callers and tests before changing shared helpers or public configuration.
- Keep changes scoped; do not modify generated logs, caches, or mirrored skills by hand.
- Do not weaken valid tests to make a change pass. Report unrelated pre-existing failures separately.
- After edits, inspect `git diff` and `git status --short` to confirm only intended files changed.

## Keep context and tool use efficient

- Search filenames and symbols first (`rg --files`, `rg -n`); open only the owning module, its local README, and relevant tests.
- Prefer a focused test node or module, then the unit gate; use the full suite when the change warrants it.
- Avoid rereading root documentation for local implementation details; use the subsystem README linked from `src/README.md`.
- Do not invoke parallel agents for a small, single-owner change. Delegate only independent tasks with clear file boundaries.
- Give progress updates at meaningful milestones and report checks actually run, including failures.
