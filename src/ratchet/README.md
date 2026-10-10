# Incremental pre-commit ratchet

The ratchet package implements a two-layer pre-commit gate that blocks regressions on
touched files while tracking project-wide debt as a long-term trend. It runs as the
`incremental-ratchet` hook (`python -m src.ratchet`) on every pre-commit run against
`src/**/*.py`. Runtime state and baselines live in the target project under
`.br-pre-commit/ratchet/`. Shared defaults come from the `[tool.br_pre_commit.ratchet]`
section of `pyproject.toml`.

## Two-layer design

**Problem:** `mypy`/`ruff`/`radon` analyze whole files, not diff hunks. A strict "must be
100% clean on any touched file" gate turns a one-line edit to a legacy file into a forced
cleanup of every unrelated pre-existing violation in that file — a chain reaction into a
dramatically bigger diff than the change actually called for.

**Fix:** two independent layers, computed fresh on every commit — no persisted per-file
baseline to drift or merge-conflict on.

1. **Blocking gate** (`gate.py`) — per-touched-file diff. For every file touched in the
   commit, compare its own violation count (`mypy`/`ruff`/`radon`) or line count (`loc`)
   before this commit vs. after, and block only the files that got worse. "Before" comes
   from a throwaway `git worktree` checked out at `HEAD`; "after" reuses the same tool
   runs already computed for the trend layer. A regression in one file can't be masked by
   an unrelated file improving elsewhere, and there's no "first time this rule/file has
   ever been seen" loophole.
2. **Project-wide trend** (`common.py`, `baseline.py`) — `baseline*.json` files track one
   count per key, content-addressed by SHA-256. After every successful commit they resync
   to fresh counts (union of keys, lowest value kept — ratchet down only, never up). This
   layer **never blocks** — it exists purely as a long-term "is total debt trending down"
   signal and to trigger characterization-test reminders.

## Module layout

| Module | Responsibility |
|--------|----------------|
| `tools.py` | Linter execution (`ruff`, `mypy`, `radon`) and by-rule/by-file grouping; runs current and before (worktree) analyzers concurrently via `ThreadPoolExecutor` |
| `gate.py` | Per-file regression evaluation, touched-file detection, `git worktree` management, characterization-test reminder trigger |
| `common.py` | Shared types, subprocess runners (`run`/`output_run`), baseline I/O & merging, trend analysis, detail-printer registry |
| `config.py` | `RatchetConfig` model loaded from `pyproject.toml` — all tunable policy constants |
| `__main__.py` | Orchestration: the only module with stdout, git staging, and baseline file writes |
| `baseline.py` | Bootstrap entry point (`baseline_current_state`) for regenerating baselines from current state |
| `details.py` | Per-tool detail printers that re-run the specific tool on blocked files |

**Design constraints:**

- **I/O isolation** — `tools.py` and `common.py` handle all subprocess/git/file I/O; `gate.py`'s `evaluate_file_gate` is a pure function of (touched files, before/after counts)
- **Blocking vs. trend** — `gate.py:evaluate_file_gate` is the only blocking path; trend analysis (`common.py:_analyze_trend`) is informational
- **Config vs. logic** — all tunable constants live in `config.py`, loaded from `pyproject.toml`; no magic numbers in logic modules
- **LOC cap** — new files must be ≤300 lines at introduction; existing files over the cap may grow by at most a 5-line slack per commit

## Per-file blocking rules

| Tool | Rule |
| --- | --- |
| `mypy` / `ruff` / `radon` (xenon) | Zero tolerance: a touched file's own violation count may not increase at all. A new file has an implicit before of 0, so any violation in it already blocks — no special case needed. |
| `loc` | A file already over 300 lines may grow by at most a 5-line slack (`line-growth-slack`, configurable via `pyproject.toml`). A brand-new file must be ≤300 lines at introduction (the slack-diff rule alone can't cover a file with no "before"). A file crossing 300 lines for the first time in this commit isn't blocked by this rule — only the project-wide trend notices it. |

Splitting an over-limit file into two or more files is a legitimate way to get back under
the loc cap — there's no equivalent escape for `mypy`/`ruff`/`radon` since those count
actual defects, not size. Whether a split is a meaningful seam vs. arbitrary chopping is a
review norm, not a mechanical check.

Renamed files (git similarity detection, `-M`) look up their "before" state under the old
path; a file reported as newly added has no "before" lookup at all (forced to 0).

## Performance

Getting an accurate per-file "before" count for `mypy` needs the whole `src/` package as it
looked at `HEAD` (it resolves types across files, so a single file in isolation gives wrong
answers) — that means a full second `mypy`/`ruff`/`radon` pass against a temporary worktree,
on top of the pass already run for "after". This is the accepted cost of exact, driftless
per-file diffing instead of a persisted per-line baseline. `loc`'s before/after comes from
`git show HEAD:path` line counts instead — no worktree, no extra tool run.

## Keys (measures)

Trend baselines track one count per key, split per rule/error code so the trend stays
legible as rules are added or removed over time. This has no effect on blocking, which is
entirely the per-file gate above.

| Key | Tool | Counts |
| --- | --- | --- |
| `mypy:code` | `mypy --config-file pyproject.toml .` (run from `src/`) | one key per bracketed `[code]` on each `error:` line; lines with no code fall into `mypy:uncoded` |
| `ruff:code` | `ruff check src --output-format=json` | one key per violation's `code` field |
| `xenon` | `radon cc src -j` | single count: blocks ranked worse than `B` (configurable via `xenon-max-absolute`, default `B`) |
| `loc` | walks `src/**/*.py` | single count: sum of `max(0, line_count - 300)` per file |

## Keeping the trend baseline current

After every successful (non-blocked) commit, the trend baseline is updated by unioning the
existing baseline(s) with the just-measured counts: every key present in either set is kept
(keys are never dropped, even at 0), and the **lowest** (best) value wins. If the result
differs from the prior baseline, it is written as a new `baseline_<hash>.json` file
(SHA-256 content hash as filename suffix, avoiding merge conflicts across parallel
branches) and staged in the same commit — no threshold, no lazy accumulation.

At the **start** of every run, if more than one `baseline*.json` file exists (e.g. from
parallel branches merged into one), they are merged (union + min), the old files are
removed, and the consolidated result is written as a single new hashed file. With only one
file on disk, no consolidation happens — it is read as-is.

## Why not per-line `# noqa` / `# type: ignore` baselines

Those mark _specific lines_ as pre-existing debt, which is precise but requires generating
and maintaining a per-line baseline file that drifts every time a legacy file is edited
(even unrelated changes shift line numbers). The per-file gate gets the same precision
(which file actually regressed) without that drift, by recomputing both sides fresh from
git every run; the project-wide trend count is coarser but self-maintaining for the same
reason.

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for implementation notes, manual operations
(bootstrapping/resetting baseline keys), the upgrade backlog, and the mutation-safety
policy.
