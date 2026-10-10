# Development notes

Internal notes for developers working on the ratchet package. For the user-facing design
overview, see [README.md](README.md).

## Bootstrapping / resetting a baseline key

Delete (or edit) its entry in any `baseline*.json` file and run `python -m src.ratchet`
once — it remeasures and records the current count as the new trend baseline for that key,
same as first-time setup. Alternatively, call `common.baseline_current_state()` directly,
or use the dedicated entry point `python -m src.ratchet.baseline` (shell wrapper:
`baseline.sh`, PowerShell: `baseline.ps1`). This only affects the trend layer; there's
nothing to bootstrap for the per-file gate since it is recomputed fresh every run.

## Mutation-safety policy

Fixing a real violation (not just formatting/import-order nits) means touching legacy code
by hand, risking silently changing behavior while "just satisfying the linter." This
repo's safeguard is test discipline, not a mutation-testing tool (see the `test-strategy`
skill's characterization-test discipline): pin the function's _current actual_ output with
a characterization test before changing it.

Whenever a commit lowers the trend baseline for any key, the ratchet checks whether the
same commit touches a tests/ directory and prints a reminder (not a block) if it doesn't —
a nudge, not a gate, per the "policy only" decision for this repo. In the current code,
`common._print_trends` calls `gate.characterization_test_touched` to perform this check.

## Inline implementation notes

### Design

Two layers: a per-touched-file before/after diff is the blocking gate (zero tolerance for
mypy/ruff/xenon, a 5-line slack for loc on files already over the 300-line cap, a hard
300-line cap for brand-new files). A project-wide count per key is kept only as a trend
metric — it never blocks, so an unrelated file improving elsewhere can't mask a regression
in the file you touched, and there's no "first time this rule/file has ever been seen"
loophole the way a project-wide-only baseline would have.

### mypy_run cwd choice

`tools.mypy_run` deliberately runs with `cwd = root / ratchet_config.target_dir_rel_path`
(i.e. `cwd=src`), not the repo root. This repo's modules import each other bare (e.g.
`from helper.paths import ...`, matching pytest's `pythonpath`), so mypy needs `src/`
itself as its implicit search-path root. Running from repo root with target `"src"` makes
every file resolve under two conflicting module names (via `explicit_package_bases` finding
repo-root vs `src/` as the package base, since `src/__init__.py` exists) and mypy aborts
("found twice"). The same reasoning applies to the "before" run against the `HEAD` worktree
— it's invoked the same way, rooted at the worktree instead of the repo root.

### ruff filename is absolute, unlike mypy/radon

`ruff check --output-format=json` reports each violation's `filename` as an absolute path,
while `mypy` and `radon cc -j` both report paths relative to their invocation `cwd`.
`tools._group_ruff_by_file` relativizes against whichever root that particular run used
(repo root for "after", the temporary worktree for "before") so both sides key on the same
`src/...` strings before comparing.

### xenon excludes tests and archive

Cyclomatic complexity isn't a meaningful signal for test code (parametrized/assert-heavy
loops are idiomatic there, not a design smell), so `src/tests/` is excluded via
`radon -i tests,...`. `archive_not_used_trash/` is unreachable-from-presentation code kept
for reference, not linted — see `<exclude_dir>/README.md` for the rationale and the
`exclude-dir` config in `pyproject.toml`.

## Analysis and upgrade plan

The old monolithic `ratchet_check.py` has been refactored into the modular layout
described in [README.md](README.md). The findings below were originally written against
that old file and have been adapted to the current module structure. Each finding notes its
current status.

### Architecture overview

```
__main__.py:main()
  ├── gate._validate_configured_hooks()                    ← warn on unregistered hooks
  ├── common.load_and_consolidate_baselines()              ← merge baseline*.json (union+min); consolidate if >1
  ├── gate.touched_app_python_files()                      ← git diff --cached --name-status -M
  ├── common._collect_analyzer_results(touched, ...)
  │     ├── gate._head_worktree() if touched               ← throwaway checkout at HEAD
  │     ├── tools._run_current_and_before_analyzers(worktree)
  │     │     ├── tools.ruff_run / mypy_run / xenon_run / loc_line_counts  ("after")
  │     │     └── same tools.*(..., before_root=worktree)                  ("before")
  │     └── gate._remove_worktree(worktree)                  ← cleanup
  ├── common.get_current_counts(...)                         ← group by rule → trend keys
  ├── common._analyze_trend(old_baseline, current_counts)    ← bootstrap/regressed/improved (info only)
  ├── common._file_gate_blocked(touched, ...)               ← gate.evaluate_file_gate() (BLOCKING)
  │     ├── tools._group_*_by_file(...)                      ← group after results by file
  │     └── gate.evaluate_file_gate(touched, after_by_file, before_by_file)
  │           ├── gate._tool_regressions()                  ← mypy/ruff/xenon: block if after > before
  │           └── gate._loc_regression()                    ← loc: block if over cap+slack; new file cap
  ├── if blocked: common._print_blocked() → DETAIL_PRINTERS → details.print_*_details()
  ├── common.compute_new_baseline(old, current)              ← union + min (never drops vectors)
  ├── common._write_new_baseline(...)                       ← write baseline_<hash>.json if changed + git add
  └── common._print_trends(regressed, improved, gate.characterization_test_touched)
```

Note: `loc` is not in `after_by_file` — the loc gate uses `common.count_lines` on the
current file and `gate._head_line_count` for the before state, both computed independently
of the mypy/ruff/xenon grouping.

### Detailed findings

#### F1 — silent tool-failure masking (P0)

**Status: Still open.**

**Now also applies to the "before" worktree runs:** `gate._head_worktree` silently returns
`None` on any `git worktree add` failure (`gate.py:55`), which
`common._collect_analyzer_results` (`common.py:288-292`) treats as "no HEAD to compare
against" — every touched file's `mypy`/`ruff`/`xenon` before-count falls back to 0, making
the gate strictly stricter (blocks more, on the file's raw current count) rather than
silently passing — the safe failure direction, but still unannounced.

**Location:** `run` (`common.py:199-202`), `output_run` (`common.py:209-212`), all tool
runners (`tools.py:ruff_run`, `mypy_run`, `xenon_run`, `loc_line_counts`).

**Weakness:** `subprocess.run(..., check=False)` ignores non-zero exit codes. If `mypy`,
`ruff`, or `radon` is not installed, crashes, or times out, the function receives empty
stdout and returns 0 — silently passing the commit. `run` also discards `result.stderr`
entirely; `output_run` concatenates it but callers only look for success patterns.

**Upgrade:**
- Add `result.check_returncode()` (or at least inspect `result.returncode`) and raise a
  descriptive `RuntimeError` when the tool exits non-zero.
- Add a per-tool timeout (e.g. `timeout=300`) so a hung `mypy` on a pathological file does
  not freeze the commit indefinitely.
- When stdout cannot be parsed, treat it as an error, not as "0 problems".

**Factor:** correctness / error handling. Hot path: yes — runs every commit. Mutation-safety: N/A (behavioral fix — wrong answers become loud failures instead of silent passes).

#### F2 — duplicate project-wide vs. detail-count logic (P1)

**Status: Resolved by refactoring.**

The old `*_count`/`*_detail_count` split no longer exists. The per-file-diff redesign
replaced "staged-file detail counters" with by-rule/by-file groupings
(`tools._group_ruff_by_rule`/`_group_ruff_by_file`, `_group_mypy_by_rule`/`_group_mypy_by_file`,
`_xenon_total`/`_group_xenon_by_file`, `loc_excess_total`/`_head_line_count`) derived from
single parsed results per tool (`ruff_run`/`mypy_run`/`xenon_run`/`loc_line_counts`), reused
for both the trend layer and the blocking gate. The specific duplication F2 flagged is gone.
The `run`/`output_run` split (see F9) is still untouched and still applies.

#### F3 — zero automated tests for the gate itself (P0)

**Status: Partially covered.**

`tests/unit/ratchet/test_ratchet_check.py` now exists and covers rule-code/by-file grouping,
`touched_app_python_files` (including renames), `evaluate_file_gate` (zero-tolerance,
new-file handling, the loc slack/cap/already-over-300 scoping, renamed-file before-lookup),
bootstrap, the trend layer never blocking on its own, an actual touched-file regression
blocking, baseline resync, and the characterization-test reminder. Not covered:
`gate._head_worktree`/`gate._remove_worktree` against a real git repo (exercised live in
this session, not in the suite), and cases 7-9 below (loud failure on tool crash /
malformed baseline / unparseable output), which are still open — they depend on F1, which
hasn't been implemented.

#### F4 — hardcoded constants that belong in config (P1)

**Status: Resolved (constants extracted to config.py).**

`RATCHET_IMPROVEMENT_RATIO`/`chunk_size` are gone: the baseline now fully resyncs to the
fresh counts after every successful commit instead of waiting for a 3% threshold, so there's
no ratio/chunk_size left to configure. All remaining constants live in `config.py`
(`RatchetConfig`), loaded from `pyproject.toml [tool.br_pre_commit.ratchet]`:

| Old constant | New location |
| --- | --- |
| `TARGET = "app"` | `config.py:ratchet_config.target_dir_rel_path` (`Path("src")`); `pyproject.toml` `target = "src"` |
| `COMPLEXITY_RANKS = "ABCDEF"` | `config.py:ratchet_config.xenon_complexity_ranks` |
| `max_lines: int = 300` | `config.py:ratchet_config.loc_max_lines`; `pyproject.toml` `max-lines = 300` |
| `max_absolute: str = "B"` | `config.py:ratchet_config.xenon_max_absolute`; `pyproject.toml` `xenon-max-absolute = "B"` |
| `RATCHET_IMPROVEMENT_RATIO = 0.03` | removed (full resync every commit) |

`xenon_complexity_ranks` can stay as a constant (it is an enum, not a policy knob) —
document that it is `"ABCDEF"` because radon uses single-letter A–F ranks.

#### F5 — fragile baseline write and git-staging race (P1)

**Status: Still open.**

**Location:** `write_baseline_file` (`common.py:156-164`), called from
`common._write_new_baseline` (`common.py:219-222`) and `common.load_and_consolidate_baselines`
(`common.py:185-191`).

**Weakness:**
1. `path.write_text()` is not atomic — if the process receives SIGTERM mid-write, the
   baseline file is left truncated/partial, breaking every subsequent commit until manually
   fixed.
2. `subprocess.run(["git", "add", ...])` stages the file unconditionally whenever
   `bootstrapped or ratcheted`. If the hook itself fails later (e.g. `main()` raises after
   the write), the user ends up with a partially staged baseline file in their index.
3. If two commits run the ratchet concurrently (e.g. two terminals), both read the same
   baseline, both compute new values, and the last writer wins — potentially losing a
   ratchet the other commit just earned.

**Upgrade:**
- Write to a temp file in the same directory, then `os.replace()` (atomic on POSIX) onto
  the final path.
- Stage the baseline file only after the full `main()` logic succeeds and the return value
  is confirmed as 0 (pass). Better: return the path to stage and let the caller (the hook
  wrapper) stage it, separating the check from the mutation.
- For the concurrency case: add a simple advisory lock (e.g. `fasteners.InterProcessLock` or
  a `.lock` file with `fcntl.flock`) around the read-modify-write of the baseline.

**Factor:** correctness / concurrency. Hot path: yes — runs every commit. Mutation-safety: pending — the "stage only on success" split changes the hook wrapper's contract and needs the tests from F3 first.

#### F6 — regex and JSON parsing fragility (P2)

**Status: Partially resolved.**

**Location:** mypy regexes in `config.py:18-19` (`mypy_coded_error_re`,
`mypy_uncoded_error_re`), used in `tools._parse_mypy_records` (`tools.py:50-58`); ruff
parsing in `tools._parse_ruff_json` (3-26); xenon parsing in `tools._parse_xenon_json`
(81-85); xenon rank lookup in `tools._xenon_total` (111) and `_group_xenon_by_file` (121).

**Weakness:** The old `re.search(r"Found (\d+) error", stdout)` count regex is gone — mypy
records are now parsed per-line via config-driven regexes (`mypy_coded_error_re` captures the
`[code]` bracket, `mypy_uncoded_error_re` catches lines with no code). However, `run`/
`output_run` still don't check return codes (F1) — a crashed mypy would silently return
empty and parse to `[]`. For xenon, `block.get("rank") or "A"` silently accepts a missing
key, defaulting to "A" (least complex) without any warning.

**Upgrade:**
- For xenon, change `block.get("rank") or "A"` to an explicit default with a logged warning
  when the key is missing, so a radon API change is visible.
- The mypy regex fragility is resolved by the per-line parsing approach, but F1 (return
  code checking) is still needed to catch crashes.

**Factor:** robustness. Hot path: yes. Mutation-safety: N/A (parsing tightening; current default of 0 on miss is the bug being fixed).

#### F7 — `_exclude_tests` inconsistency (P2)

**Status: Resolved by refactoring.**

The old inconsistency was that `xenon_count` (project-wide, included tests) and
`xenon_detail_count` (staged-only, excluded tests) measured different scopes. In the current
code, both `_xenon_total` and `_group_xenon_by_file` consume the output of `xenon_run`
(`tools.py:88-101`), which applies the same `-i tests,archive_not_used_trash` exclusion. The
scope is now consistent. The separate `_exclude_tests` function (`tools.py:138-140`) is only
used by `details.print_xenon_details` for detail display, not for counting.

#### F8 — `loc` scope drift (P2)

**Status: Still open.**

**Location:** `tools.loc_line_counts` (`tools.py:128-135`) vs. `gate._head_line_count`
(`gate.py:119-129`).

**Weakness:** `loc_line_counts` walks the target dir excluding `__pycache__` and
`exclude_dir_regex` but does **not** exclude `tests/`. `loc_excess_total`
(`tools.py:143-144`) uses this — so the project-wide loc count includes test files. The
before-state uses `git show HEAD:path` line counts in `_head_line_count`, which counts the
staged file's lines directly (no directory walk, no exclusions). Meanwhile xenon explicitly
excludes tests. This means loc and xenon measure different scopes: loc counts test-file
growth, xenon doesn't.

**Upgrade:** Apply the same exclusion policy to both functions. The xenon scope
("tests excluded") is documented in the inline notes above. If tests are excluded from
xenon, they should probably be excluded from loc too for consistency. If the decision is to
keep tests in the loc count, document that explicitly.

**Factor:** correctness / policy clarity. Hot path: yes. Mutation-safety: pending — changing the baseline's meaning requires a one-time baseline key deletion per affected vector so the new count is bootstrapped cleanly.

#### F9 — `run` / `output_run` duplication and stderr swallowing (P2)

**Status: Still open.**

**Location:** `run` (`common.py:199-202`), `output_run` (`common.py:209-212`).

**Weakness:** Two functions that differ only in whether they append `result.stderr`. Every
caller that needs stderr uses `output_run` (e.g. `mypy_run` in `tools.py:63`); every caller
that doesn't uses `run` (e.g. `ruff_run`, `xenon_run`). This split means `run` silently
swallows stderr, hiding tool warnings that may indicate a problem.

**Upgrade:** Collapse into one `_run(args, cwd, include_stderr=False)` with a flag. Always
capture stderr (it's cheap) and let callers pick. Prefer `include_stderr=True` for
diagnostic tools like mypy.

**Factor:** duplication/simplification. Hot path: yes. Mutation-safety: N/A (mechanical).

#### F10 — `__main__.py` path & config resolution (P3)

**Status: Resolved.**

The old `ROOT = Path(__file__).resolve().parents[3]` fragile path arithmetic is gone. All
modules now use `get_user_repo_path_from_env()` from `helper/paths.py`, which reads the repo
root from environment variables set by the pre-commit hook wrapper. This is robust to
folder restructuring and works correctly in both development and hook contexts.

#### F11 — no CLI / dry-run / verbosity (P3)

**Status: Partially resolved.**

**Location:** `__main__.py:main` (`__main__.py:40-72`), `baseline.py:main`
(`baseline.py:22-26`).

**Weakness:** `__main__.py:main()` is invoked as `python -m src.ratchet` with no argparse
interface — it always runs with defaults, always writes baselines, always stages them, and
always prints at one verbosity. `baseline.py:main()` provides a separate entry point for
baseline regeneration but also has no CLI flags.

**Upgrade:** Add a minimal `argparse` interface to `__main__.py`:
```
python -m src.ratchet [--dry-run] [--verbose]
```
Keep the zero-argument default behavior unchanged so the existing pre-commit hook wiring
(`.pre-commit-config.yaml` entry `python -m src.ratchet`) does not need to change.

**Factor:** usability / testability. Hot path: N/A. Mutation-safety: N/A.

#### F12 — detail printing only for blocked files (P3)

**Status: Resolved by refactoring.**

The old `print_regression_details` (only printed for blocked vectors) is now
`common._print_blocked` (`common.py:340-361`), which prints details for every blocked file.
The trend layer (`common._print_trends`, `common.py:370-393`) reports both regressed and
improved vectors independently of the gate. The "ignored regression" concept (project-wide
up, staged count == 0) doesn't map directly — the trend layer never blocks by design, so
there's no "ignored" state to surface.

#### F13 — wrong module reference in details.py (P0)

**Status: Found during merge — needs fix.**

**Location:** `details.py:17` imports `from . import baseline as _baseline`, but `baseline.py`
only defines `main` and re-exports `baseline_current_state` and `find_baseline_files` from
`common`. The detail printers use `_baseline.run_output` (`details.py:26`),
`_baseline.run` (`details.py:47`), and `_baseline._line_count` (`details.py:74`) — none of
which exist on the `baseline` module. They live in `common` instead.

Additionally, `details.py:74` calls `_baseline._line_count(...)` but `common.py` defines
`count_lines` (not `_line_count`) — there is no `_line_count` function anywhere in the
package.

The docstring (`details.py:6-8`) is also stale: it says "through the `baseline` module" and
references `_line_count`, when the intended target is the `common` module and the function
is `count_lines`.

**Weakness:** If `print_loc_details` (or `print_ruff_details` / `print_xenon_details`) is
called — triggered when the loc/ruff/xenon gate blocks — it raises `AttributeError`. This
is masked because the codebase is currently clean and the gate never blocks, so these
printers are never exercised in normal operation. The test suite (`test_ratchet_check.py`)
does not cover the detail printers.

**Upgrade:**
- Change `from . import baseline as _baseline` to `from . import common as _baseline` in
  `details.py:17`.
- Change `_baseline._line_count(...)` to `_baseline.count_lines(...)` in `details.py:74`.
- Update the docstring (`details.py:6-8`) to reference `common` and `count_lines`.

**Factor:** correctness. Hot path: no (only on block). Mutation-safety: N/A (behavioral fix — functions that can't currently be called due to the bug become functional).

#### F14 — stale test-directory paths in characterization_test_touched (P2)

**Status: Found during merge — needs fix.**

**Location:** `gate.py:143-146` (`characterization_test_touched`).

**Weakness:** The function checks for `app/tests/{characterization,unit,regression}/` paths,
but the target directory changed from `app` to `src` and tests live under `tests/` at the
repo root (not `src/tests/`). The hardcoded `app/tests/` prefix will never match, so the
characterization-test reminder never fires.

**Upgrade:** Update the test directory prefixes to match the actual layout (`tests/unit/`,
`tests/integration/`, `tests/e2e/`, or whatever the characterization tests use).

**Factor:** correctness. Hot path: no (only prints a reminder). Mutation-safety: N/A.

### Prioritized upgrade todo

| id | priority | title | key files |
|----|----------|-------|-----------|
| T1 | P0 | Add tests for uncovered gate branches (worktree, loud failure, malformed baseline) | `tests/unit/ratchet/` |
| T2 | P0 | Make tool failures loud (returncode check, timeouts) | `common.py`, `tools.py` |
| T13 | P0 | Fix wrong module reference in details.py | `details.py` |
| T3 | P1 | (Resolved) Constants moved to `config.py` | `config.py`, `pyproject.toml` |
| T4 | P1 | (Resolved) Duplication collapsed into shared helpers | `tools.py` |
| T5 | P1 | Atomic baseline write + stage only on success + inter-process lock | `common.py:write_baseline_file` |
| T8 | P2 | (Resolved) `_exclude_tests` scope mismatch fixed | `tools.py:xenon_run` |
| T9 | P2 | Clarify and align `loc_line_counts` test exclusion policy | `tools.py`, `gate.py` |
| T14 | P2 | Fix stale test-directory paths in `characterization_test_touched` | `gate.py` |
| F6/T7 | P2 | Harden xenon rank parsing; warn on missing keys | `tools.py` |
| T6 | P2 | Unify `run`/`output_run`; always capture stderr | `common.py` |
| T10 | P3 | (Resolved) Path resolution uses env-based `get_user_repo_path_from_env` | `common.py` |
| T11 | P3 | Add argparse CLI with `--dry-run`, `--verbose` | `__main__.py` |
| T12 | P3 | (Resolved by separation) Trend and gate details are independent | `common.py` |

### Recommended execution order

1. **T1 (P0, tests)** — extend the test suite first. Every later refactor is gated by
   these tests passing.
2. **T2 (P0, loud failures)** — add returncode checks and timeouts. The new tests should
   now catch the silent-pass bug.
3. **T13 (P0, details.py bug)** — fix the wrong module reference and `_line_count` typo.
4. **T5 (P1, atomic write + lock)** — fix the baseline write race. Run tests.
5. **T9 + T14 (P2, scope fixes)** — fix loc test exclusion and characterization-test paths.
   Document any baseline reset needed.
6. **T6 (P2, run/output_run unification)** — collapse the duplication. Run tests.
7. **F6/T7 (P2, parse robustness)** — harden xenon rank parsing. Run tests.
8. **T11 (P3, CLI)** — add argparse interface.

### Mutation-safety policy for this code

This code runs on every commit. The repo's own policy is "test discipline, not mutation
testing." Apply that here:

- **T1 must land before any other item.** Without tests, a refactor to T2/T5/T6 is
  unguarded.
- **T5's baseline-meaning change** (T9: fixing scope mismatches) requires a one-time
  `baseline*.json` key deletion per affected vector so the new count is bootstrapped
  cleanly — document that in the commit message.
- **T2's loud-failure change** is behavior-preserving for the success path (same counts,
  same block decision) but changes the failure path from silent-pass to loud-fail. That is
  the intended fix, not a regression, but it should be called out in the commit message.

## Related references

- [README.md](README.md) — design rationale and vector table (this package's README)
- `pyproject.toml` `[tool.br_pre_commit.ratchet]` — current config (target, loc cap, slack,
  xenon rank, exclusions)
- `src/ratchet/config.py` — `RatchetConfig` model with validation aliases
- `tests/unit/ratchet/test_ratchet_check.py` — existing test coverage for grouping and gate
- `.pre-commit-config.yaml` § `incremental-ratchet` — hook wiring (`python -m src.ratchet`)
- `docs/development/FEATURE_ANALYSIS.md` — feature analysis (references to old paths may be
  stale; cross-check with current module layout)
- `.kilo/skills/pre-commit-check/SKILL.md` — pre-commit skill, references the ratchet hook
