# incremental pre-commit ratchet

The implementation now lives in this repository at
`src/ratchet/__main__.py`. Runtime repository
state and baselines stay in the target project under `.br-pre-commit/ratchet/`.
Shared defaults come from the `[tool.br_pre_commit.ratchet]` section of
`pyproject.toml`.

- [per-file blocking rules](#per-file-blocking-rules)
- [performance](#performance)
- [keys](#keys)
- [keeping the trend baseline current](#keeping-the-trend-baseline-current)
- [mutation-safety note](#mutation-safety-note)
- [bootstrapping / resetting a key](#bootstrapping--resetting-a-key)
- [why not per-line baselines](#why-not-per-line-baselines)
- [ratchet_check.py — analysis and upgrade plan](#ratchet_checkpy--analysis-and-upgrade-plan)

Problem: `mypy`/`radon` analyze whole files, not diff hunks. A strict "must be 100% clean on any touched file" gate turns a one-line edit to a legacy file into a forced cleanup of every unrelated pre-existing violation in that file - a chain reaction into a dramatically bigger diff than the change actually called for.

Fix: two independent layers, computed fresh on every commit - no persisted per-file baseline to drift or merge-conflict on.

1. **Blocking gate - per-touched-file diff.** For every file touched in the commit, compare its own violation count (`mypy`/`ruff`/`xenon`) or line count (`loc`) before this commit vs. after, and block only the files that got worse. "Before" comes from a throwaway `git worktree` checked out at `HEAD` (removed again right after); "after" reuses the same tool runs already computed for the trend layer below - no extra invocation needed there. A regression in one file can't be masked by an unrelated file improving elsewhere in the same commit, and there's no "first time this rule/file has ever been seen" loophole - see the rules table.
2. **Trend metric - project-wide aggregate.** `baseline*.json` files track one count per key project-wide and resync to the fresh counts after every successful commit. Vectors are never removed — a key that drops to zero stays in the baseline at 0, ratcheting the bar permanently. Each resync writes a new `baseline_<hash>.json` file (content-addressed by a SHA-256 suffix, so parallel branches never collide) instead of overwriting a single file; at the start of every run, multiple baseline files are merged (union of keys, lowest value kept) into one and the old files are removed. This layer **never blocks** - it exists purely as a long-term "is total debt trending down" signal and to decide when to remind about characterization tests (see below).

## per-file blocking rules

| tool | rule |
| --- | --- |
| `mypy` / `ruff` / `xenon` | zero tolerance: a touched file's own violation count may not increase at all. A new file has an implicit before of 0, so any violation in it already blocks - no special case needed. |
| `loc` | a file already over 300 lines may grow by at most a 5-line slack (`LOC_SLACK`) - not a hard freeze, so a small legitimate fix isn't blocked outright. A brand-new file must be ≤300 lines at introduction (the slack-diff rule alone can't cover a file with no "before"). A file crossing 300 lines for the first time in this commit isn't blocked by this rule - only the non-blocking project-wide sum notices it. |

Splitting an over-limit file into two or more files is a legitimate way to get back under the loc cap - there's no equivalent escape for `mypy`/`ruff`/`xenon` since those count actual defects, not size. Whether a split was a meaningful seam vs. arbitrary chopping to dodge the check isn't something line counts alone can judge - left as a review norm, not a mechanical check.

Renamed files (git similarity detection, `-M`) look up their "before" state under the old path; a file reported as newly added has no "before" lookup at all (forced to 0 / no prior line count).

## performance: this doubles mypy/ruff/xenon's runtime on commits touching `app/*.py`

Getting an accurate per-file "before" count for `mypy` needs the whole `app/` package as it looked at `HEAD` (it resolves types across files, so a single file in isolation gives wrong answers) - that means a full second `mypy`/`ruff`/`radon` pass against a temporary worktree, on top of the pass already run for "after". This is the accepted cost of exact, driftless per-file diffing instead of a persisted per-line baseline file (see "why not per-line baselines" below). `loc`'s before/after comes from `git show HEAD:path` line counts instead - no worktree, no extra tool run.

## keys (trend / ratchet-down input only - not the blocking gate)

| key | tool | counts |
| --- | --- | --- |
| `mypy:code` | `mypy --config-file pyproject.toml app` | one key per bracketed `[code]` on each `error:` line; lines with no code fall into `mypy:uncoded` |
| `ruff:code` | `ruff check app --output-format=json` | one key per violation's `code` field |
| `xenon` | `radon cc app -j` | single count: blocks ranked worse than `B` (configurable via `ratchet.xenon-max-absolute`, default `B`) |
| `loc` | walks `app/**/*.py` | single count: sum of `max(0, line_count - 300)` per file |

`mypy`/`ruff` are split per rule/error code so the trend stays legible as rules are added or removed over time (each code bootstraps/retires independently) - this has no effect on blocking, which is entirely the per-file gate above.

## keeping the trend baseline current

After every successful (non-blocked) commit, the trend baseline is updated by unioning the existing baseline(s) with the just-measured counts: every key present in either set is kept (keys are never dropped, even when their count falls to zero), and for each key the **lowest** (best) value wins. If the result differs from the prior baseline, it is written as a new `baseline_<hash>.json` file (SHA-256 content hash as filename suffix, avoiding merge conflicts across parallel branches) and staged in the same commit - no threshold, no lazy accumulation.

At the **start** of every run, if more than one `baseline*.json` file exists (e.g. from parallel branches merged into one), they are merged (union + min), the old files are removed, and the consolidated result is written as a single new hashed file. With only one file on disk, no consolidation or rewriting happens - the single file is read as-is.

## mutation-safety note (no new tool - policy only)

Fixing a real violation (not just a formatting/import-order nit) means touching legacy code by hand, which risks silently changing behavior while "just satisfying the linter." This repo's safeguard for that is test discipline, not a mutation-testing tool (see the `test-strategy` skill's characterization-test discipline): pin the function's _current actual_ output with a characterization test before changing it. Whenever a commit lowers the trend baseline for any key (something got fixed), `ratchet_check.py` checks whether the same commit touches `app/tests/{characterization,unit,regression}/` and prints a reminder (not a block) if it doesn't - a nudge, not a gate, per the "policy only" decision for this repo.

## bootstrapping / resetting a key

Delete (or edit) its entry in any `baseline*.json` file and run `python ratchet_check.py` once - it re-measures and records the current count as the new trend baseline for that key, same as first-time setup. This only affects the trend layer; there's nothing to bootstrap for the per-file gate since it's recomputed fresh every run.

## why not per-line `# noqa`/`# type: ignore` baselines instead

Considered (e.g. `mypy-baseline`, ignore-comment sprinkling) and rejected: those mark _specific lines_ as pre-existing debt, which is more precise but requires generating and maintaining a per-line baseline file that drifts every time a legacy file is edited (even unrelated changes shift line numbers). The per-file gate gets the same precision (which file actually regressed) without that drift, by recomputing both sides fresh from git every run instead of persisting anything; the project-wide trend count is coarser but self-maintaining for the same reason.

## inline commentary

### design

Incremental pre-commit ratchet - see README.md in this folder for the full design.

Two layers: a per-touched-file before/after diff is the blocking gate (zero tolerance for mypy/ruff/xenon, a 5-line slack for loc on files already over the 300-line cap, a hard 300-line cap for brand-new files). A project-wide count per key is kept only as a trend metric feeding the mutation-safety reminder - it never blocks a commit by itself, so an unrelated file improving elsewhere can't mask a regression in the file you touched, and there's no "first time this rule's been seen" loophole the way a project-wide-only baseline would have.

### mypy_count cwd choice

`cwd=app` (not ROOT, target "app") deliberately: this repo's modules import each other bare (`from ai_modelling.base import ...`, matching pytest.ini's pythonpath=app - see the pytest skill's "Repo config" section), so mypy needs app/ itself as its implicit search-path root. Running from ROOT with target="app" made every file resolve under two conflicting module names (via explicit_package_bases finding repo-root vs app/ as the package base, since app/**init**.py exists) and mypy aborted after 1 file ("found twice"). The same reasoning applies to the "before" run against the `HEAD` worktree - it's invoked the same way, rooted at the worktree instead of `ROOT`.

### ruff filename is absolute, unlike mypy/radon

`ruff check --output-format=json` reports each violation's `filename` as an absolute path, while `mypy` and `radon cc -j` both report paths relative to their invocation `cwd`. `_group_ruff_by_file` relativizes against whichever root that particular run used (repo root for "after", the temporary worktree for "before") so both sides key on the same `app/...` strings before comparing.

### xenon excludes tests and archive

Cyclomatic complexity isn't a meaningful signal for test code (parametrized/assert-heavy loops are idiomatic there, not a design smell), so app/tests/ is excluded entirely - see docs/infrastructure.md#incremental-ratchet-mypyruffxenon-scope. archive_not_used_trash/ is unreachable-from-presentation code kept for reference, not linted - see app/archive_not_used_trash/README.md.

## ratchet_check.py — analysis and upgrade plan

### Architecture overview

```
main()
  ├── load_and_consolidate_baselines()                 ← merge baseline*.json (union + min); consolidate if >1
  ├── run ruff/mypy/xenon once each ("after") + loc_line_counts()
  ├── group each into by-rule dicts -> current_counts (trend layer)
  │     compare vs. old_baseline: bootstrap / regressed_trend (info only) / improved (info only)
  ├── touched_app_python_files()                    ← git diff --cached --name-status -M
  ├── if touched:
  │     ├── group the same "after" runs into by-file dicts
  │     ├── _head_worktree()                        ← throwaway checkout at HEAD
  │     ├── run ruff/mypy/xenon again in the worktree -> by-file "before" dicts
  │     ├── evaluate_file_gate(touched, after, before):
  │     │     mypy/ruff/xenon: block if after > before (0 for new files)
  │     │     loc: block if before>300 and after > before+5; new file must be <=300
  │     └── remove the worktree
  ├── block (exit 1) if evaluate_file_gate found anything - this is the ONLY blocking path
  ├── else: compute_new_baseline(old_baseline, current_counts) = union + min (never drops vectors)
  │     write baseline_<hash>.json if changed + git add it
  └── print regressed_trend (info) / improved+characterization reminder / OK summary
```

### Detailed findings

#### F1 — silent tool-failure masking (P0)

**Now also applies to the "before" worktree runs**: `_head_worktree()` silently returns `None` on any `git worktree add` failure, which `main()` treats as "no HEAD to compare against" - i.e. every touched file's `mypy`/`ruff`/`xenon` before-count falls back to 0, meaning a broken worktree setup makes the gate strictly stricter (blocks more, on the file's raw current count) rather than silently passing - the safe failure direction, but still unannounced. `run()`/`run_output()`'s underlying weakness (below) affects both the "after" run and this "before" run identically.

**Location**: `run()` (`ratchet_check.py:39-41`), `run_output()` (`ratchet_check.py:44-46`), all count functions (`mypy_count`, `ruff_count`, `xenon_count`, `loc_count`).

**Weakness**: `subprocess.run(..., check=False)` ignores non-zero exit codes. If `mypy`, `ruff`, or `radon` is not installed, crashes, or times out, the function receives an empty stdout and returns 0 — silently passing the commit. `run()` also discards `result.stderr` entirely; `run_output()` concatenates it but the callers only look for success patterns.

**Upgrade**:
- Add `result.check_returncode()` (or at least inspect `result.returncode`) and raise a descriptive `RuntimeError` when the tool exits non-zero.
- Add a per-tool timeout (e.g. `timeout=300`) so a hung `mypy` on a pathological file does not freeze the commit indefinitely.
- When stdout cannot be parsed, treat it as an error, not as "0 problems".

**Factor**: correctness / error handling. Hot path: yes — runs every commit. Mutation-safety: N/A (behavioral fix — wrong answers become loud failures instead of silent passes).

#### F2 — duplicate project-wide vs. detail-count logic (P1)

**Superseded**: the old `*_count`/`*_detail_count` split this item described no longer exists - the per-file-diff redesign replaced "staged-file detail counters" with by-rule/by-file groupings (`_group_ruff_by_rule`/`_group_ruff_by_file`, etc.) derived from a single parsed result per tool (`ruff_run`/`mypy_run`/`xenon_run`), reused for both the trend layer and the blocking gate. The specific duplication F2 flagged is gone; the `run`/`run_output` split (below) is still untouched and still applies.

**Location**: `mypy_count` / `mypy_detail_count` (`ratchet_check.py:49-59` vs. `ratchet_check.py:131-137`), `ruff_count` / `ruff_detail_count` (`ratchet_check.py:62-68` vs. `ratchet_check.py:148-156`), `xenon_count` / `xenon_detail_count` (`ratchet_check.py:75-89` vs. `ratchet_check.py:183-195`), `loc_count` / `loc_detail_count` (`ratchet_check.py:92-99` vs. `ratchet_check.py:211-216`).

**Weakness**: Each vector has two near-identical functions that differ only in whether they operate on all project files or a filtered `paths` list. The `run` / `run_output` split and the JSON-parsing / regex-parsing blocks are also duplicated. Four vectors × two variants = eight functions where four would suffice with a shared `count_violations(tool, paths=None)` helper.

**Upgrade**:
- Introduce a `_count_violations(vector_name, paths=None)` helper that accepts an optional file list and delegates to the tool with either the project target or the explicit paths.
- Collapse `run` and `run_output` into a single `_run(args, cwd, capture_stderr=False)` with a flag, or always capture both and let callers pick.
- Share the JSON-decode / regex-match / rank-filter logic in one place per vector.

**Factor**: duplication/simplification. Hot path: yes — called every commit. Mutation-safety: pending — extract carefully; add regression tests for the helper before collapsing (see F3).

#### F3 — zero automated tests for the gate itself (P0)

**Partially covered**: `tests/unit/git_hooks/test_ratchet_check.py` now exists and covers rule-code/by-file grouping, `touched_app_python_files` (including renames), `evaluate_file_gate` (zero-tolerance, new-file handling, the loc slack/cap/already-over-300 scoping, renamed-file before-lookup), bootstrap, the trend layer never blocking on its own, an actual touched-file regression blocking, baseline resync, and the characterization-test reminder. Not covered: `_head_worktree`/`_remove_worktree` against a real git repo (exercised live in this session, not in the suite), and cases 7-9 below (loud failure on tool crash / malformed baseline / unparseable output), which are still open - they depend on F1, which hasn't been implemented.

**Location**: entire file.

**Weakness**: The incremental ratchet is the single highest-trust component in the pre-commit pipeline — if it breaks, every commit either silently passes bad code or blocks good code — yet there are no tests for it anywhere under `app/tests/`. The four vectors, the baseline-bootstrap path, the ratchet-down threshold, the ignored-regression branch, and the characterization-test reminder are all untested.

**Upgrade**:
- Add `tests/unit/git_hooks/test_ratchet_check.py` (or `tests/regression/...` given the file's role as infrastructure).
- Test cases:
  1. Baseline missing → bootstraps at current count, does not block.
  2. Current count == baseline → passes.
  3. Current count < baseline but < 3% improvement → records improvement, does not ratchet.
  4. Current count < baseline and >= 3% improvement → ratchets baseline, stages file.
  5. Project-wide regression + staged regression → blocks with exit code 1.
  6. Project-wide regression + zero staged regression → passes (ignored regression branch).
  7. Tool not installed / exits non-zero → loud failure, not silent pass.
  8. `baseline.json` malformed → loud failure, not silent pass.
  9. `mypy` output format change (no "Found N error" match) → treated as parse error, not 0.
  10. Characterization-test reminder prints when ratcheting without touching test dirs.
- Use `unittest.mock` to mock `subprocess.run`, `Path.exists`, `Path.read_text`, `Path.write_text`, and `staged_app_python_files` so tests run without real tools or git state.

**Factor**: correctness / coverage. Hot path: yes — runs every commit. Mutation-safety: required — write these tests before any other refactor (F2, F4, F5).

#### F4 — hardcoded constants that belong in config (P1)

**Resolved by removal, not by wiring config.json in.** `RATCHET_IMPROVEMENT_RATIO`/`chunk_size` are gone: baseline.json now fully resyncs to the fresh counts after every successful commit instead of waiting for a threshold, so there's no ratio/chunk_size left to configure. `config.json` was deleted. See `scripts/git-hooks/incremental-precommit/README.md` § "keeping baseline current". The rest of this item (below) is left for history; `TARGET`/`COMPLEXITY_RANKS`/`max_lines`/`max_absolute` are still hardcoded and the config-extraction idea still applies to those if wanted later.

**Location**: `RATCHET_IMPROVEMENT_RATIO = 0.03` (`ratchet_check.py:30`), `TARGET = "app"` (`ratchet_check.py:28`), `COMPLEXITY_RANKS = "ABCDEF"` (`ratchet_check.py:29`), `max_lines: int = 300` in `loc_count` / `loc_detail_count` (`ratchet_check.py:92,211`), `max_absolute: str = "B"` in `xenon_count` / `xenon_detail_count` (`ratchet_check.py:75,183`).

**Weakness**: `config.json` held only `chunk_size: 3` (this doc and the README each cited a different, wrong default before the resolution above). The ratchet improvement threshold, the xenon rank ceiling, the loc line threshold, and the target directory are all hardcoded in the script despite being policy decisions that already have prose documentation in `infrastructure.md` and the README. Moving them to `config.json` makes them editable without touching code and keeps policy and implementation in one place.

**Upgrade** (for the still-hardcoded constants only - `chunk_size`/`ratchet_improvement_ratio` no longer apply, see the resolution note above):
- Introduce a `config.json` schema, if wanted:
  ```json
  {
    "xenon_max_absolute": "B",
    "loc_max_lines": 300,
    "target": "app"
  }
  ```
- Load these values in `main()` or at module level, falling back to the current defaults when keys are absent.
- `COMPLEXITY_RANKS` can stay as a constant (it is an enum, not a policy knob), but document why it is `"ABCDEF"` and not a longer/shorter string.

**Factor**: configuration / policy coupling. Hot path: N/A (read once per commit). Mutation-safety: N/A (defaults preserve current behavior; missing keys fall back to current hardcoded values).

#### F5 — fragile `baseline.json` write and git-staging race (P1)

**Location**: `BASELINE_PATH.write_text(...)` (`ratchet_check.py:311-312`).

**Weakness**:
1. `write_text` is not atomic — if the process receives SIGTERM mid-write, `baseline.json` is left as a truncated/partial file, breaking every subsequent commit until someone manually fixes it.
2. `subprocess.run(["git", "add", ...])` stages the file unconditionally whenever `bootstrapped or ratcheted`. If the hook itself fails later (e.g. `main()` raises after the write), the user ends up with a partially staged `baseline.json` in their index — a confusing state.
3. If two commits run the ratchet concurrently (e.g. two terminals), both read the same baseline, both compute new values, and the last writer wins — potentially losing a ratchet the other commit just earned.

**Upgrade**:
- Write to a temp file in the same directory, then `os.replace()` (atomic on POSIX) onto `baseline.json`.
- Stage `baseline.json` only after the full `main()` logic succeeds and the return value is confirmed as 0 (pass). Better: return the path to stage and let the caller (the hook wrapper) stage it, separating the check from the mutation.
- For the concurrency case: add a simple advisory lock (e.g. `fasteners.InterProcessLock` or a `.lock` file with `fcntl.flock`) around the read-modify-write of `baseline.json`.

**Factor**: correctness / concurrency. Hot path: yes — runs every commit. Mutation-safety: pending — the atomic-replace and lock changes are mechanical, but the "stage only on success" split changes the hook wrapper's contract and needs the tests from F3 first.

#### F6 — regex and JSON parsing fragility (P2)

**Location**: `re.search(r"Found (\d+) error", stdout)` in `mypy_count` (`ratchet_check.py:58`) and `mypy_detail_count` (`ratchet_check.py:136`).

**Weakness**: The regex assumes mypy's exact English output phrasing `"Found N error"`. A mypy version bump that switches to `"Found N errors"` (plural), `"N error(s) found"`, or a localized output would cause the regex to return `None` and the function to silently return 0. `ruff`'s JSON parsing already handles the empty/invalid case, but `xenon`'s rank lookup uses `block.get("rank", "A")` which silently accepts a missing key.

**Upgrade**:
- Prefer machine-readable flags over text parsing: `mypy --show-error-codes --no-error-summary --json` (mypy 1.0+ exposes `--show-traceback` and JSON output modes; if not available, the regex should at least be case-insensitive and accept both singular/plural).
- If JSON output is unavailable, make the regex more defensive: `re.search(r"Found\s+(\d+)\s+error", stdout, re.IGNORECASE)` and log a warning when the match is `None` instead of returning 0.
- For `xenon`, change `block.get("rank", "A")` to an explicit default with a logged warning when the key is missing, so a radon API change is visible.

**Factor**: robustness. Hot path: yes — runs every commit. Mutation-safety: N/A (parsing tightening; current default of 0 on miss is the bug being fixed).

#### F7 — `_exclude_tests` inconsistency (P2)

**Location**: `xenon_detail_count` calls `_exclude_tests(paths)` (`ratchet_check.py:184`), but `xenon_count` does not (`ratchet_check.py:75-89`).

**Weakness**: The project-wide xenon count includes test files and `archive_not_used_trash`, while the staged-only xenon detail count excludes them. This means a regression detected by `xenon_count` may be "ignored" by `xenon_detail_count` not because staged files are clean, but because the project-wide count includes files that the detail count filters out. The two counts are measuring different scopes but are compared against the same baseline.

**Upgrade**: Either exclude tests/archive from both, or include them in both. The README and `infrastructure.md` describe xenon's scope as `app/` (excluding tests), so the project-wide `xenon_count` should call `_exclude_tests` too. Alternatively, make the exclusion list configurable and apply it uniformly.

**Factor**: correctness. Hot path: yes. Mutation-safety: pending — changing the baseline's meaning requires a baseline reset (document the reset step).

#### F8 — `loc_count` scope drift (P2)

**Location**: `loc_count` (`ratchet_check.py:92-99`) vs. `loc_detail_count` (`ratchet_check.py:211-216`).

**Weakness**: `loc_count` walks `(ROOT / TARGET).rglob("*.py")` and excludes `__pycache__` and `archive_not_used_trash`, but does **not** exclude `tests/`. `loc_detail_count` counts only staged paths (which are already filtered by `staged_app_python_files` to exclude `archive_not_used_trash` but not `tests/`). The project-wide loc count can grow because of test-file growth, but the detail count on a given commit may not reflect that — same scope mismatch as F7.

**Upgrade**: Apply the same exclusion policy to both functions. The `infrastructure.md` loc policy does not explicitly exclude tests, but if tests are excluded from xenon they should probably be excluded from loc too for consistency. If the decision is to keep tests in the loc count, document that explicitly and ensure `loc_detail_count` includes them too.

**Factor**: correctness / policy clarity. Hot path: yes. Mutation-safety: pending (baseline meaning change).

#### F9 — `run` / `run_output` duplication and stderr swallowing (P2)

**Location**: `run()` (`ratchet_check.py:39-41`), `run_output()` (`ratchet_check.py:44-46`).

**Weakness**: Two functions that differ only in whether they append `result.stderr`. Every caller that needs stderr uses `run_output`; every caller that doesn't uses `run`. This split means:
- `run` silently swallows stderr, hiding tool warnings that may indicate a problem.
- Adding a new caller requires choosing between the two, with no clear rule.

**Upgrade**: Collapse into one `_run(args, cwd, include_stderr=False)` that always captures stderr and returns either stdout or stdout+stderr based on the flag. Always-include-stderr is also safer because tool warnings (e.g. ruff's `"warning: ..."`) are not lost.

**Factor**: duplication/simplification. Hot path: yes. Mutation-safety: N/A (mechanical).

#### F10 — hardcoded `ROOT` path resolution fragility (P3)

**Location**: `ROOT = Path(__file__).resolve().parents[3]` (`ratchet_check.py:24`).

**Weakness**: The script assumes it lives exactly three directory levels below the repo root (`scripts/git-hooks/incremental-precommit/` → parents[3] = repo root). If the file is moved or the folder structure changes, `ROOT` silently points to the wrong directory. `HERE` is robust (relative to the file itself), but `ROOT` is not.

**Upgrade**: Compute `ROOT` from a repo marker (e.g. walk up from `HERE` looking for `.git/`, `pyproject.toml`, or a known directory like `app/`). This is a common pattern:
```python
ROOT = HERE
while not (ROOT / "pyproject.toml").exists() and ROOT != ROOT.parent:
    ROOT = ROOT.parent
```
Alternatively, accept `ROOT` as an environment variable override for non-standard layouts.

**Factor**: robustness. Hot path: N/A (computed once). Mutation-safety: N/A.

#### F11 — no CLI / dry-run / verbosity controls (P3)

**Location**: `main()` (`ratchet_check.py:252-333`).

**Weakness**: The script has no CLI interface — it always runs with defaults, always writes `baseline.json`, always stages it, and always prints at the same verbosity. There is no way to:
- Run it in dry-run mode to see what would happen without mutating `baseline.json`.
- Override the config path or baseline path for testing.
- Increase verbosity to debug why a particular vector regressed.

**Upgrade**: Add a minimal `argparse` (or `click`) interface:
```
ratchet_check.py [--config PATH] [--baseline PATH] [--dry-run] [--verbose]
```
Keep the zero-argument default behavior unchanged so the existing pre-commit hook wiring (`scripts/git-hooks/pre-commit`) does not need to change.

**Factor**: usability / testability. Hot path: N/A. Mutation-safety: N/A.

#### F12 — `print_regression_details` only prints for actually regressed vectors (P3)

**Location**: `print_regression_details` (`ratchet_check.py:234-243`).

**Weakness**: The function takes `regressed` (only the vectors that blocked) and prints details only for those. For `ignored_regressions` (project-wide up, staged count == 0), the user sees a one-line summary but no detail on *which* staged files would have triggered the regression if they had been touched — useful context for understanding why the vector is drifting.

**Upgrade**: Optionally print details for `ignored_regressions` too, or add a `--verbose` flag (see F11) that surfaces them. Not a bug, but a missed observability opportunity.

**Factor**: usability. Hot path: N/A. Mutation-safety: N/A.

### Prioritized upgrade todo

| id | priority | title | key files |
|----|----------|-------|-----------|
| T1 | P0 | Add unit/regression tests for all ratchet branches | new `tests/.../test_ratchet_check.py` |
| T2 | P0 | Make tool failures loud instead of silent (return-code check, timeouts) | `run`, `run_output`, all count functions |
| T3 | P1 | Move configurable constants into `config.json` (ratio, loc threshold, xenon rank, target) | `config.json`, `ratchet_check.py` |
| T4 | P1 | Collapse project-wide / detail-count duplication into a shared helper per vector | `ratchet_check.py` |
| T5 | P1 | Make `baseline.json` write atomic + stage only on full success + add inter-process lock | `ratchet_check.py`, hook wrapper |
| T6 | P2 | Unify `run` / `run_output`; always capture stderr | `ratchet_check.py` |
| T7 | P2 | Harden `mypy` regex and xenon rank parsing; log on parse failure instead of returning 0 | `mypy_count`, `mypy_detail_count`, `xenon_count`, `xenon_detail_count` |
| T8 | P2 | Fix `_exclude_tests` scope mismatch between `xenon_count` and `xenon_detail_count` | `xenon_count`, `_exclude_tests` |
| T9 | P2 | Clarify and align `loc_count` / `loc_detail_count` test exclusion policy | `loc_count`, `loc_detail_count` |
| T10 | P3 | Replace `parents[3]` `ROOT` resolution with walk-up-from-file or env-var override | `ratchet_check.py:24` |
| T11 | P3 | Add `argparse` CLI with `--dry-run`, `--config`, `--baseline`, `--verbose` | `main()` |
| T12 | P3 | Print ignored-regression details for observability (behind `--verbose`) | `print_regression_details`, `main` |

### Recommended execution order

1. **T1 (P0, tests)** — write the test suite first. Every later refactor (T2–T12) is gated by these tests passing.
2. **T2 (P0, loud failures)** — add return-code checks and timeouts. Run the new tests; they should now catch the silent-pass bug.
3. **T3 (P1, config)** — move constants to `config.json` with backward-compatible defaults.
4. **T4 (P1, DRY)** — collapse the eight count functions into four shared helpers. Run tests.
5. **T5 (P1, atomic write + lock)** — fix the baseline write race. Run tests.
6. **T6–T9 (P2, hardening)** — parse robustness, scope fixes.
7. **T10–T12 (P3, polish)** — path resolution, CLI, observability.

### Mutation-safety policy for this file

This file runs on every commit. The repo's own policy (see `infrastructure.md` and the ratchet README) is "test discipline, not mutation testing." Apply that here:

- **T1 must land before any other item**. Without tests, a refactor to T2–T5 is unguarded.
- **T5's baseline-meaning change** (T7/T9: fixing scope mismatches) requires a one-time `baseline.json` key deletion per affected vector so the new count is bootstrapped cleanly — document that in the commit message.
- **T2's loud-failure change** is behavior-preserving for the success path (same counts, same block decision) but changes the failure path from silent-pass to loud-fail. That is the intended fix, not a regression, but it should be called out in the commit message.

### Related references

- `scripts/git-hooks/incremental-precommit/README.md` — design rationale and vector table.
- `docs/infrastructure.md` § incremental ratchet — policy and threshold rationale.
- `scripts/git-hooks/incremental-precommit/config.json` — current (minimal) config.
- `docs/todos/code_optimization.md` — existing optimization backlog format (P0/P1/P2/P3 tiers).
- `docs/todos/data_pipeline_upgrade_plan.md` — existing upgrade-plan format.
