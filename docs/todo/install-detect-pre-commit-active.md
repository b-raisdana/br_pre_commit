# TODO: Upgrade install.sh / install.ps1 to detect existing pre-commit

## Goal

`install.sh` and `install.ps1` should detect whether pre-commit is already active
in the target repository. If it is, the installer must preserve the repo's
existing pre-commit configuration and layer `br_pre_commit` controls on top of
it. If it is not active, the installer performs a fresh install as it does
today.

## Current behaviour

Both installers unconditionally overwrite `.git/hooks/pre-commit` with a shim
that calls `br_pre_commit/run` (or `run.ps1`). They do not inspect:

- whether the `pre-commit` Python package is installed,
- whether a `.pre-commit-config.yaml` exists,
- whether a pre-commit hook is already present in `.git/hooks/`.

This means a project that already had pre-commit set up loses its hook
configuration on re-install, and the wrapper cannot run usefully without a
`.pre-commit-config.yaml` (the wrapper reads hook IDs from it at runtime).

## Desired behaviour

### Detection

Before writing the hook, the installer checks (in order):

1. `pre-commit` is importable / on PATH in the active Python environment.
2. A `.pre-commit-config.yaml` exists in the repo root.
3. A pre-commit hook already exists at `.git/hooks/pre-commit`.

If all three are true, pre-commit is considered **already active**.

### Branches

**A. pre-commit already active**

- Do **not** clobber the existing `.git/hooks/pre-commit` shim.
- Instead, install the `br_pre_commit` wrapper as a *separate* hook file,
  e.g. `.git/hooks/br_pre_commit_pre_commit`, and make the existing hook
  call it, or install the wrapper in a way that composes with the existing
  hook. The cleanest approach is to wrap the existing hook: back it up to
  `.git/hooks/pre-commit.orig` (only if not already backed up) and replace
  `.git/hooks/pre-commit` with a shim that runs the original first, then
  runs `br_pre_commit/run` (or vice versa, depending on policy).
- Ensure `BR_PRE_COMMIT_REPO_ROOT` and `BR_PRE_COMMIT_TOOL_ROOT` are exported
  in the new shim.
- Print a message indicating pre-commit was detected and that the existing
  hook was preserved (backed up to `pre-commit.orig`).

**B. pre-commit NOT active (fresh install)**

- Behave exactly as today: overwrite `.git/hooks/pre-commit` with the
  `br_pre_commit` shim.
- Print a message indicating a fresh install was performed.

## Files to change

| File | Change |
|------|--------|
| `install.sh` | Add detection logic + branching (A/B) above. |
| `install.ps1` | Mirror the same detection logic + branching. |
| `docs/todo/install-detect-pre-commit-active.md` | This file (the plan). |

## Edge cases to handle

- The existing hook is **already** the `br_pre_commit` shim (re-install).
  Detect this by inspecting the hook contents for the
  `BR_PRE_COMMIT_TOOL_ROOT` marker; treat as "already active, no-op".
- The existing hook is a **different** pre-commit hook (e.g. standard
  `pre-commit install` output). Back it up and wrap it.
- `pre-commit` is installed but no `.pre-commit-config.yaml` exists → treat
  as fresh install (the wrapper will surface a clear runtime error if hooks
  are invoked without a config).
- No `pre-commit` package at all → fresh install; the wrapper still works
  for branch protection and backup even if `pre-commit run` cannot execute.
- Repo is on a protected branch (`main`) at install time → the fresh-install
  verification step should still succeed; branch protection only blocks
  commits, not hook execution.

## Verification

1. Fresh repo (no pre-commit): `install.sh` writes the shim and reports a
   fresh install.
2. Repo with `pre-commit install` already run: `install.sh` detects the
   existing hook, backs it up to `pre-commit.orig`, and wraps it.
3. Re-running `install.sh` on an already-wrapped repo is idempotent: it
   detects the `br_pre_commit` marker and no-ops (or re-wraps cleanly
   without double-wrapping).
4. Same scenarios on Windows via `install.ps1`.

## Open questions (to be answered before implementation)

- Should the wrapper run **before** or **after** the existing pre-commit
  hook? (Recommendation: existing hook first, then `br_pre_commit`, so
  project hooks get a chance to mutate files before the wrapper's
  concurrent/backup logic runs.)
- Should the backup snapshot be taken before or after the existing hook
  runs? (Recommendation: after, so the snapshot reflects the post-hook
  state.)
- How should the wrapper report that it is running in "layered" mode vs.
  "fresh" mode? (Recommendation: a log line at startup, e.g.
  `mode=layered` vs `mode=fresh`, written to the run log.)
