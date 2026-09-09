# Incremental pre-commit ratchet

`src/br_pre_commit/incremental_precommit/ratchet_check.py` is the quality
trend gate every tracked Python project runs as a local pre-commit hook. It is
the shared infrastructure; the consumer project owns only its hook selection
and its baseline files.

The ratchet is built on **two independent layers**, both computed fresh on
every commit:

1. A **blocking per-touched-file gate** — the only thing that can fail a commit.
2. A **project-wide trend baseline** — a long-term "is total debt trending
   down?" signal that **never blocks**.

## Why two layers?

Tools like `mypy` and `ruff` analyze whole files, not diff hunks. A strict
"any touched file must be 100% clean" gate turns a one-line edit to a legacy
file into a forced cleanup of every unrelated pre-existing violation in that
file — a chain reaction into a dramatically larger diff than the change
actually called for.

- The **per-file gate** prevents that: it only blocks files that *got worse*
  in this commit, comparing each touched file's own count before vs. after.
- The **trend layer** still catches the case where debt quietly accumulates
  across many files — it just does not block; it reports and locks in
  improvements.

## The blocking gate: per-touched-file before/after

**What counts as "touched":** `git diff --cached --name-status -M --diff-filter=ACMR`
restricted to files under the ratchet target (default `app/`) ending in `.py`.
Renames (`-M`) are resolved so a renamed file's "before" is looked up under its
old path; a genuinely added file has no "before" lookup. Files inside
`archive_not_used_trash/` are skipped.

**"Before" state** is a throwaway `git worktree add --detach HEAD` at a
temporary directory — the whole `app/` package at `HEAD` so cross-file type
resolution is accurate. The worktree is removed immediately after the gate
runs, in a `finally` block.

| Tool | Rule |
|---|---|
| `mypy` / `ruff` / `xenon` | **Zero tolerance.** A touched file's count may not increase at all. A new file has an implicit before of `0`, so any violation in it already blocks — no special case needed. |
| `loc` | A brand-new file must be ≤ `max-lines` (default `500`). A file already over the cap may grow by at most `line-growth-slack` lines (default `5`). A file *crossing* the cap for the first time in this commit is **not** blocked by the gate — only the (non-blocking) project-wide sum notices it. |

An oversized file can be split into two or more files to fit under the `loc`
cap — a legitimate way through this gate, but a meaningful seam rather than
arbitrary chopping to dodge the check.

If the worktree cannot be created (e.g. git is unavailable), the gate falls
back to a strict before-of-`0` for every touched file — the safe failure
direction (blocks more, never silently passes).

If the gate blocks, it prints each offender as
`<tool> in <path>: <before> -> <after>` plus per-tool detail (the raw tool
output for those files) and exits `1`.

## The trend layer: project-wide aggregate

For each tool, a per-rule (or per-category) count is computed across the whole
project:

| key | tool | counts |
|---|---|---|
| `mypy:<code>` | `mypy --config-file pyproject.toml .` (run from `app/`) | one key per bracketed `[code]`; uncoded errors fall into `mypy:uncoded` |
| `ruff:<code>` | `ruff check app --output-format=json` | one key per violation `code` |
| `xenon` | `radon cc app -j -i tests,archive_not_used_trash --show-closures` | single count: blocks ranked worse than `B` |
| `loc` | walks `app/**/*.py` (excludes `__pycache__`, `archive_not_used_trash`) | sum of `max(0, lines - 500)` per file |

`mypy`/`ruff` are split per rule code so the trend stays legible as rules are
added or removed over time; this does not affect blocking, which is entirely
the per-file gate above.

**Resync.** After every successful (non-blocked) commit, the trend baseline is
updated by unioning the existing baseline(s) with the just-measured counts:
every key present in either set is kept (keys are **never** dropped, even when
their count falls to zero — the bar ratchets permanently down), and for each
key the **lowest** (best) value wins. If the result differs from the prior
baseline, it is written as a new `baseline_<hash>.json` and staged in the same
commit.

**Conflict-free across branches.** Baselines are content-addressed: the
filename suffix is the first 8 hex chars of a SHA-256 of the JSON content, so
parallel branches never collide on the same file. At the **start** of every
run, if more than one `baseline*.json` exists they are merged (union + min),
the old files are removed, and the consolidated result is written as a single
new hashed file. With only one file on disk, nothing is rewritten.

The trend layer **never blocks** — it reports
`regressed_trend` (project-wide rose) and `improved` (project-wide dropped,
locked in as the new baseline) as informational output only.

## Settings

All thresholds come from `defaults.toml`, overlayed recursively by the consumer
project's optional `.br-pre-commit.toml`. There is no per-project code change
required to adjust them — see `project-settings.example.toml` for commented
examples. The relevant keys:

```toml
# defaults.toml
[ratchet]
target = "app"
max-lines = 500
line-growth-slack = 5
complexity-ranks = "ABCDEF"
```

## Characterization-test reminder

When a commit **improves** the trend baseline for any key (something got
fixed), the ratchet checks whether the same commit touches
`app/tests/{characterization,unit,regression}/`. If it does not, it prints a
reminder — not a block — to pin the before/after behavior with a
characterization test first, since behavior-affecting fixes risk silent
mutation. This repo's mutation-safety net is **test discipline**, not a
mutation-testing tool.

## Bootstrapping / resetting a key

Delete (or edit) its entry in any `baseline*.json` and run the ratchet once —
it re-measures and records the current count as the new trend baseline. There
is nothing to bootstrap for the per-file gate since it is recomputed fresh
every run. A new vector key is also bootstrapped automatically on first
encounter.

## See also

- Design rationale and upgrade notes: [RATCHET.md](../RATCHET.md)
- Consumer integration (the local `incremental-ratchet` hook entry):
  [hook-installer.md](hook-installer.md)
