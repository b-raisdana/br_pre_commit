# git-hooks

- [Backup & recovery](#backup--recovery)
- [Pre-commit gap analysis](#pre-commit-gap-analysis)
- [Pre-commit improvement plan](#pre-commit-improvement-plan)

The clone-local `.git/hooks/pre-commit` shim is installed with `bash ../br_pre_commit/install.sh "$PWD"` from a target project.

The installed hook delegates to `src/br_pre_commit/precommit_wrapper.py`. Before running project hooks, the wrapper blocks branches listed by `wrapper.protected-branches` (`["main"]` by default). It then reads the target project's `.pre-commit-config.yaml`, uses one shared staged-files context, runs file-mutating hooks serially, and runs read-only hooks in concurrent subprocesses. Unknown hooks fail by default (`wrapper.unknown-hook-policy` in `.br-pre-commit.toml`); `warn` runs them serially. Each job has the configured timeout.

The hook IDs the wrapper can classify are defined as frozensets in `precommit_config.py` (`_MUTATING_HOOKS` and `_READ_ONLY_HOOKS`); see README.md § "Recognized hook IDs" for the full list and the requirement that every project config use only registered IDs.

- **logging**: stdout/stderr stream live to stdout with job prefixes and remain in per-job RAM buffers. After all jobs stop, `logs/pre-commit/pre-commit-runs/<timestamp>.log` receives an ordered per-job report; `pre-commit.log` receives the JSON-line summary.
- **advisory lint warnings**: `Q`/`RUF`/`T10`/`T20`/`ERA` (quote conventions, Ruff-specific likely-bug checks, debugger statements, print() calls, commented-out code) plus radon maintainability index (MI) are deliberately left out of `pyproject.toml`'s `[tool.ruff.lint] select` - no VS Code squiggle, no incremental-ratchet gate. They're still surfaced as non-blocking stdout warnings plus an `advisory_lint_warnings` field in the log entry.
- **failure backup**: after all failed jobs stop, [backup.py](src/br_pre_commit/backup.py) runs in a dedicated subprocess and takes a read-only snapshot of staged, unstaged, and untracked state under `logs/pre-commit/backup-patches/<branch>.<short_commit>/`. Async Git subprocesses fetch metadata and per-file diffs concurrently; thread-offloaded writes/copies do not block the event loop. Backup never mutates shared Git state. Patches include a 7-hex CRC-32 content identifier so changed versions coexist; identical patches replace their prior copy and refresh its mtime. The snapshot also contains raw untracked copies and a `manifest.json`; use [recover.py](src/br_pre_commit/recover.py) to restore it.

[recover.py](src/br_pre_commit/recover.py) is the only script allowed to touch shared git state. It reads the snapshot's `manifest.json` and reapplies staged changes via `git apply --cached`, unstaged changes via `git apply`, and untracked files via raw copy. Its mutating steps are wrapped in an advisory file lock (`.git/recover.lock`, `fcntl.flock` with a short timeout) so concurrent sensitive operations can detect each other. The lock is advisory, not mandatory.

## Backup & recovery

### Design rationale

Backup intentionally avoids touching any shared git state during backup (`HEAD`, the index, `refs/stash`, `refs/heads/`). This makes it safe to run concurrently with itself and with other git operations - a pre-commit hook or agentic process can snapshot at any moment without racing. Recovery is the only step that mutates git state, and it is invoked deliberately by a human or agent responding to a detected failure.

### backup.py

Pure read-only async snapshot. Allowed Git commands: `git diff`, `git diff --cached`, `git ls-files`, and `git rev-parse`.

Snapshot layout under `logs/pre-commit/backup-patches/`:

```
logs/pre-commit/backup-patches/
  <branch>.<short_commit>/
    manifest.json
    staged/<relative-path>.<content-hash>.patch
    unstaged/<relative-path>.<content-hash>.patch
    untracked/<relative-path>
```

- **Staged**: `git diff --cached -- <path>` → content-addressed `.patch`
- **Unstaged**: `git diff -- <path>` → content-addressed `.patch`
- **Untracked**: raw copy → no suffix

Per-file error handling: if one file fails, it is recorded as `"failed"` in the manifest and the script continues.

Logs a one-line summary: snapshot path, counts, total size.

### recover.py

Restores working state from a backup snapshot. CLI:

```
python3 recover.py --snapshot <path-to-snapshot-dir> \
                    [--to-commit] \
                    [--only staged|unstaged|untracked] \
                    [--dry-run] \
                    [--repo <repo-root>]
```

- `--to-commit`: checkout the snapshot's commit before reapplying (use when the working branch has moved on).
- `--only`: restrict reapply to one category.
- `--dry-run`: print what would be done without touching anything.

Behavior:
1. Read `manifest.json`. Refuse to proceed if missing or malformed.
2. If `--to-commit`, run `git checkout <commit_hash>` under the advisory lock.
3. Reapply staged files with `git apply --cached <patch>`.
4. Reapply unstaged files with `git apply <patch>`.
5. Reapply untracked files by copying bytes to their original path.
6. If any `git apply` fails, stop and report exactly which file failed and why. Partial recovery with a clear error beats silent full failure.
7. Print a final summary and remind the user the snapshot directory is left on disk untouched.

## Pre-commit gap analysis

Current pre-commit covers: formatting/ hygiene (`pre-commit-hooks`), lint + format (`ruff`), type checking (`mypy --strict`), complexity (`xenon` via `radon cc`), line-count ratchet (`loc`), unit tests (`pytest -m unit`), pandera decorator check, and skill-file sync.

What is missing, grouped by category:

### Security

- **secret scanning**: no hook catches committed API keys, passwords, or tokens. Add `detect-secrets` or `gitleaks` as a pre-commit hook (blocking). This is the highest-priority gap — a single committed secret is a permanent repo-level leak.
- **dependency CVEs**: `pip-audit` or `safety` is absent. `tensorflow[and-cuda]` has frequent advisories. Add as a weekly scheduled check (not per-commit) that blocks only on high/critical.
- **in-code security patterns**: `bandit` is absent. Catches `eval`, `pickle`, hardcoded credentials, weak crypto. Add as a ratchet-tracked vector (like mypy/ruff), not a per-file strict gate.

### Dead code and unused symbols

- **vulture**: no dead-code scanner. A 36 kLOC codebase with an `archive_not_used_trash/` folder has accumulated unused functions, classes, and imports. Add as a non-blocking pre-commit hook (warnings only) because false positives are common in dynamic paths (`getattr`, `__import__`).
- **ruff unused imports/variables**: partially covered by `F401`/`F841`, but `RUF100` (stale `# noqa`) is not enabled.

### Dependency hygiene

- **deptry**: no unused-dependency detector. `requirements.txt` / `requirements-dev.txt` / `pyproject.toml` can accumulate stale packages as the code evolves. Add as a weekly check, not per-commit.

### Documentation coverage

- **interrogate / pydocstyle**: no docstring coverage or style enforcement. This repo has mixed docstring coverage. Add `interrogate` first (coverage metric, weekly report), then `pydocstyle` once coverage is above 80%.

### Ruff rule coverage gaps

Current `select = ["E", "F", "I", "UP", "B", "C4", "SIM", "W"]` is missing high-value rules:

| Module | Missing rules | Risk |
|--------|--------------|------|
| `RUF` | `RUF001`–`003` (ambiguous unicode), `RUF005` (inefficient unpacking), `RUF010` (function call in default arg), `RUF012` (mutable class default), `RUF015` (`next()` on iterable) | Bug-risk |
| `T10` | `T100` (debugger breakpoint) | Debug hygiene |
| `ERA` | `ERA001` (commented-out code) | Maintainability |
| `ANN` | `ANN001` (missing return type), `ANN002` (missing `self`/`cls` type), `ANN101` (missing `self`) | Type clarity |
| `N` | `N802`, `N806` (PEP 8 naming) | Style consistency |
| `C90` | `C901` (McCabe complexity) | Currently handled by `xenon`/`radon`; should move to ruff |

### Mypy strictness gaps

Current config: `strict = true`, `disallow_any_explicit = true`, `ignore_missing_imports = true`. Still missing:

- **`strict_equality = true`**: catches `if x == True:` and `== None`.
- **`no_implicit_reexport = true`**: wildcard imports must be explicit.
- **`disallow_any_unimported`**: blocked by missing stubs for `ccxt`, `pandas_ta`, `prophet`. Revisit when stubs land.

### CI / scheduling gaps

- **no CI workflow**: pre-commit is local-only (`--no-verify` bypasses it). There is no GitHub Actions (or equivalent) CI that runs the full suite on PRs. The fast gate should be promoted to a required CI check.
- **no scheduled scans**: `pip-audit`, `deptry`, `interrogate`, and full `pytest` should run on a schedule (weekly/nightly) because they are too slow or broad for per-commit.

### Recommended priority order

1. **P0 — add `detect-secrets`** (blocking hook, one-time historical scan first).
2. **P0 — enable `RUF` + `ERA` + `C90` in ruff**, remove `xenon`/`radon`.
3. **P1 — add `bandit`** (ratchet-tracked, start with `--exit-zero` for one week).
4. **P1 — add `vulture`** (non-blocking warnings).
5. **P2 — add `pip-audit`** (weekly, block on high/critical).
6. **P2 — add `deptry`** (weekly report).
7. **P3 — add `interrogate`** (weekly, target 80% coverage).
8. **P3 — add CI workflow** running the full gate on every PR.

## Pre-commit improvement plan

Current state: `.pre-commit-config.yaml` + `pyproject.toml` + `scripts/git-hooks/incremental-precommit/ratchet_check.py` gate four project-wide vectors (`ruff`, `mypy`, `xenon`, `loc`) through an incremental ratchet that blocks only regressions in committed `baseline.json`. Ruff selects `E,F,I,UP,B,C4,SIM,W`; xenon uses `radon cc` to count cyclomatic-complexity blocks ranked worse than `B` (9 in baseline); mypy runs `--strict --disallow-any-explicit` (90 errors in baseline); loc sums excess lines over 500. `archive_not_used_trash/` is excluded from all scans.

### Ruff-first principle

Prefer ruff for any static-analysis vector it can cover. Only adopt a separate tool when it measures something ruff genuinely cannot (maintainability index, comment density, security AST patterns, dependency CVEs, unused imports/code, dead dependencies). Eliminate the separate tool once ruff adds equivalent coverage — xenon is the first instance of this policy in this plan.

### Move xenon cyclomatic complexity to ruff C90

Ruff's `C901` (`complex-structure`) is a drop-in McCabe-complexity replacement for `radon cc`. It integrates with the existing ruff JSON output, shares the same `--fix`/`--output-format` pipeline, and avoids a separate `radon` install.

Changes:

- Add `C90` to `[tool.ruff.lint] select` in `pyproject.toml`.
- Set `[tool.ruff.lint.mccabe] max-complexity = 10` (matches xenon's `--max-absolute B` threshold: ranks C–F exceed 10).
- Remove `xenon` from `ratchet_check.py` `PROJECT_COUNTERS`, `DETAIL_COUNTERS`, `DETAIL_PRINTERS`, and `tool_totals`/`tool_baseline_totals`.
- Replace xenon keys in `baseline.json` with `ruff:C901` per-code keys (ruff already emits one key per violation code).
- Update `docs/infrastructure.md` § incremental ratchet and § pre-commit to remove xenon references.
- Delete `radon` from `requirements-dev.txt` (or verify it is not used elsewhere).

Current `C901` violations under the new threshold: 10 (all `C901`, default limit 10). Once enabled, these become the initial `ruff:C901` baseline entries.

Risk: low — `C901` and `radon`'s McCabe implementation produce equivalent scores for standard Python control flow. The only edge case is radon's handling of `with`/`try` blocks in some older versions; ruff follows PEP 8 / standard AST semantics.

### Add wily

`wily` measures maintainability index, cyclomatic complexity, raw LOC, Halstead volume, and comment density. None of the existing tools cover maintainability index or comment density; xenon/ruff cover complexity but not maintainability trend.

Integration:

- Add `wily` to `requirements-dev.txt`.
- Add a new `wily` vector to `ratchet_check.py`:
  - Project-wide: `wily report app --format json` (or `wily rank app`) to capture maintainability-index and complexity per module.
  - Detail: `wily report --paths <staged files> --format json`.
  - Count key: sum of modules where maintainability index drops below 20 (the standard red-line) or complexity exceeds the same `C901` threshold.
- Track one key per metric in `baseline.json`: `wily:maintainability`, `wily:complexity`.
- Add a `wily` detail printer for staged-file regression reporting.

Why wily over a hand-rolled script: wily already handles per-module aggregation, caching, and JSON output. It is the standard tool for this vector in the Python ecosystem.

### Ruff rule inventory: block vs. log

#### Priority tiers

- **Block (ratchet-tracked)**: A regression in the project-wide count that touches staged files blocks the commit. These represent real bugs, undefined behavior, or maintainability debt.
- **Log only (pre-commit hook reports, never blocks)**: Style, formatting, simplification, and modernization. Auto-fixed where possible; remaining violations are printed as warnings.

All ruff scans exclude `archive_not_used_trash/` (unreachable-from-presentation reference code — `pyproject.toml` `extend-exclude`, ratchet `_exclude_tests` logic).

#### F — Pyflakes (logical errors) — all Block

| Rule | What it checks | Rationale |
|------|---------------|-----------|
| F401 | module imported but unused | Dead import; indicates abandoned code path or incomplete refactor |
| F821 | undefined name | Runtime NameError; code cannot execute as written |
| F822 | undefined name in `__all__` | Broken public API; `from X import *` will fail |
| F823 | local variable referenced before assignment | Runtime UnboundLocalError |
| F841 | local variable assigned but never used | Dead code; likely leftover from refactor |
| F831 | local variable assigned but never used (argument variant) | Dead code in function parameters |

#### B — flake8-bugbear (potential bugs) — all Block

| Rule | What it checks | Rationale |
|------|---------------|-----------|
| B005 | `.strip()` with multi-character string | Silently strips each character, not the substring — logic bug |
| B006 | mutable default argument | Shared state across calls; classic Python gotcha |
| B007 | loop control variable not used | Likely logic error; loop body doesn't use its iterator |
| B011 | `assert False` | Should raise `AssertionError` explicitly; `assert False` can be optimized away |
| B015 | pointless comparison | Always True or False; dead code |
| B018 | useless expression | No-op statement; indicates incomplete refactor |
| B025 | `try-except-pass` | Silently swallows exceptions; hides failures |
| B026 | star-arg unpacking after keyword argument | SyntaxError in Python 3.8+; breaks at runtime |
| B028 | missing `stacklevel` in `warnings.warn` | Wrong line reported in warning output |
| B031 | missing context manager for file-like operations | Resource leak; file handle not closed on exception |
| B904 | `raise` without `from` inside `except` | Loses exception chain; harder to debug |

#### C901 — McCabe complexity — Block

| Rule | What it checks | Rationale |
|------|---------------|-----------|
| C901 | function too complex (cyclomatic complexity > 10) | Maintainability debt; hard to test and reason about |

#### RUF — Ruff-specific (Python gotchas) — all Block

| Rule | What it checks | Rationale |
|------|---------------|-----------|
| RUF001 | ambiguous unicode character in string | Looks like ASCII but is a different code point; can cause bugs in comparisons |
| RUF002 | ambiguous unicode character in docstring | Same as RUF001 but in documentation |
| RUF003 | ambiguous unicode character in comment | Same as RUF001 but in comments |
| RUF005 | iterable unpacking instead of concatenation | `[a, *b, c]` instead of `a + b + c`; unnecessary copy when b is already a list |
| RUF010 | function call in function argument default | Evaluated at definition time; can cause surprising shared state |
| RUF012 | mutable class default | Class variable that is mutable (list/dict) is shared across instances |
| RUF015 | `next()` on iterable instead of `for` loop | `next(iterable)` without default raises StopIteration; `for` is safer |
| RUF100 | unused `noqa` directive | `# noqa` comment suppresses a rule that isn't actually violated; stale suppression |

#### T10 — debugger statements — Block

| Rule | What it checks | Rationale |
|------|---------------|-----------|
| T100 | breakpoint left in code | `breakpoint()`, `pdb.set_trace()`, or `sys.breakpointhook()` call committed; halts execution in production |

#### ERA — commented-out code — Block

| Rule | What it checks | Rationale |
|------|---------------|-----------|
| ERA001 | commented-out code | Dead code in comments; directly prevents `archive_not_used_trash`-style drift |

#### E — pycodestyle errors — mostly Log, E741 Block

| Rule | What it checks | Priority | Rationale |
|------|---------------|----------|-----------|
| E501 | line too long | Log | Formatting; `ruff-format` handles this. Exclude when `ruff-format` is active. |
| E302 | expected 2 blank lines | Log | Formatting |
| E305 | expected 2 blank lines after function | Log | Formatting |
| E741 | ambiguous variable name (`l`, `O`, `I`) | Block | Visually ambiguous; can cause bugs in loops and conditionals |

#### I — isort — Log

| Rule | What it checks | Rationale |
|------|---------------|-----------|
| I001 | import block incorrectly sorted | Style; auto-fixable. Consistent import order reduces diff noise. |
| I002 | missing required import | Style; auto-fixable. |

#### UP — pyupgrade — Log

| Rule | What it checks | Rationale |
|------|---------------|-----------|
| UP006 | use `set()` instead of `set([])` etc. | Modernization; auto-fixable. Cleaner, faster syntax. |
| UP035 | import from `importlib.metadata` | Modernization; auto-fixable. Standard library replacement for `pkg_resources`. |
| UP038 | use `X \| Y` instead of `Union[X, Y]` | Modernization; auto-fixable. PEP 604 union syntax (Python 3.10+). |
| UP040 | `TypeAlias` annotation | Modernization; auto-fixable. Explicit type alias declaration (PEP 613). |

#### C4 — flake8-comprehensions — Log

| Rule | What it checks | Rationale |
|------|---------------|-----------|
| C400-C402 | unnecessary `list`/`set`/`generator` calls around comprehension | Simplification; auto-fixable. `list([x for x in y])` → `[x for x in y]`. |
| C416 | unnecessary comprehension | Simplification; auto-fixable. `{x for x in y}` → `set(y)` when `y` is already iterable. |
| C417 | unnecessary `map` | Simplification; auto-fixable. `list(map(f, iterable))` → `[f(x) for x in iterable]`. |

#### SIM — flake8-simplify — Log

| Rule | What it checks | Rationale |
|------|---------------|-----------|
| SIM102 | nested `if` statement | Simplification; auto-fixable. Merge nested conditions with `and`. |
| SIM108 | ternary operator | Simplification; auto-fixable. `if/else` assignment → `x if c else y`. |
| SIM110 | duplicate `if` branches | Simplification; auto-fixable. Merge branches with same body. |
| SIM112 | compare with tuple | Simplification; auto-fixable. `x in (a, b, c)` is clearer than chained `or`. |
| SIM114 | nested `if` with same body | Simplification; auto-fixable. Merge with `and`. |
| SIM115 | open file without context handler | Resource leak; auto-fixable. Wrap in `with` statement. |
| SIM116 | dictionary merge in loop | Simplification; auto-fixable. Use dict comprehension or `|` merge. |
| SIM117 | merge multiple `with` statements | Simplification; auto-fixable. Combine into one `with` block. |

#### W — pycodestyle warnings — Log

| Rule | What it checks | Rationale |
|------|---------------|-----------|
| W291 | trailing whitespace | Formatting; also covered by `pre-commit-hooks` `trailing-whitespace`. |
| W293 | whitespace on blank line | Formatting; also covered by `pre-commit-hooks`. |

#### ANN — type annotation presence — Log

| Rule | What it checks | Rationale |
|------|---------------|-----------|
| ANN001 | missing return type annotation | Complements mypy at the lint level; mypy infers returns but `ANN` forces explicit `-> None` on void functions |
| ANN002 | missing `self`/`cls` type in method | Complements mypy; ensures instance/class methods are typed |
| ANN101 | missing `self` annotation | Same as ANN002 for `self` specifically |
| ANN102 | missing `cls` annotation | Same as ANN002 for `cls` specifically |

#### N — PEP 8 naming — Log

| Rule | What it checks | Rationale |
|------|---------------|-----------|
| N802 | function name should be lowercase | PEP 8 naming consistency |
| N806 | variable in function should be lowercase | PEP 8 naming consistency |
| N812 | lowercase imported as non-lowercase | PEP 8 naming consistency for imports |

### Ruff module expansions beyond C90

Current select: `E,F,I,UP,B,C4,SIM,W`. Significant additions: `RUF`, `T10`, `ERA`, `ANN`, `N`. Each rule above is classified individually; the implementation order reflects priority:

1. `RUF` first (bug-risk)
2. `ERA` (maintainability)
3. `T10` (debug hygiene)
4. `ANN`/`N` (style)

Add each as a new key in `baseline.json` after measuring the project-wide count.

Not recommended now:

- `Q` (quote conventions) — deliberately excluded per current config; adding it creates churn in a large legacy codebase. Revisit once the `RUF`/`ERA` subset is stable.
- `SIM` is already enabled; `SIM910` (nested `getattr`/`setattr`) and `SIM900` (mergeable `if`) are the highest-value SIM rules and already covered.
- `C4` is already enabled; `C417` (unnecessary `map`) is the main win there.

### Mypy improvements

Current config is already `strict = true` plus `disallow_any_explicit = true` and `ignore_missing_imports = true` (90 errors in baseline). High-value deltas:

- **`warn_unused_ignores`** — already implied by `strict`, but worth verifying it is active (baseline shows 14 `mypy:unused-ignore`, confirming it is).
- **`strict_equality = true`** — catches `if x == True:` and `== None` (currently implicit under `strict` in newer mypy versions, but set explicitly to pin behavior across mypy bumps).
- **`no_implicit_reexport = true`** — wildcard imports from this repo's own modules must be explicit; prevents `from X import *` from silently pulling names.

Not recommended now:

- **`disallow_any_unimported`** — still blocked by `ccxt`, `pandas_ta`, and `prophet` (no stubs). Revisit when stubs land in typeshed or typed packages appear on PyPI.
- **`mypy` plugins for pandera** — `pandera` ships no mypy plugin; the `pandera` decorator returns a wrapped function whose type mypy cannot easily infer. A custom plugin would help but is not off-the-shelf; defer until pandera adds one.

Dependency audit: add a quarterly task to re-check whether `ccxt`/`pandas_ta`/`prophet` ship type stubs so `disallow_any_unimported` can be enabled without blanket `# type: ignore` sprinkling.

### Additional tools

#### Vulture

Finds unused code and dead imports. A 36 kLOC codebase with an `archive_not_used_trash/` folder has accumulated dead code. Vulture catches:

- Functions/classes/modules with zero external callers.
- Unused imports and variables.

Integration: add `vulture` to `requirements-dev.txt`. Run it as a non-blocking pre-commit hook (warnings only, not in the ratchet) because false positives are common in dynamic-code paths (e.g., `getattr`, `__import__`, reflection). Treat vulture output as a triage backlog, not a commit gate.

#### Deptry

Detects unused dependencies in `requirements.txt` / `requirements-dev.txt` / `pyproject.toml`. In a project where dependencies evolve (TensorFlow, pandas_ta, ccxt, pandera, duckdb, vectorbt pending), stale deps accumulate silently.

Integration: add `deptry` to `requirements-dev.txt`. Run as a weekly CI-equivalent check (not per-commit, because dependency removal is a separate review). Report unused deps to `docs/todos/deptry_backlog.md`.

#### pip-audit

Scans installed dependencies for known CVEs. This project installs `tensorflow[and-cuda]` — a high-profile package with frequent advisories. `pip-audit` (PyPA-maintained) is the standard tool.

Integration: add `pip-audit` to `requirements-dev.txt`. Run in the WSL `tf` env on a schedule (weekly or on TensorFlow bumps), not per-commit. Block only on high/critical CVEs; low/info are informational.

#### Bandit

Security linter for Python AST patterns (hardcoded secrets, `eval`, `pickle`, weak crypto, etc.). Complements `pip-audit` (dependency CVEs) with in-code pattern checks.

Integration: add `bandit` to `requirements-dev.txt`. Run as a pre-commit hook with `--exit-zero` + ratchet tracking, similar to ruff's current mode. Track project-wide counts per bandit test ID in `baseline.json`.

#### Interrogate or pydocstyle

Docstring coverage and style. This repo has mixed docstring coverage. `interrogate` measures percentage of covered functions/classes/modules; `pydocstyle` enforces PEP 257 conventions.

Recommendation: `interrogate` first (coverage metric), then `pydocstyle` if coverage reaches 80%. Integration: run `interrogate` as a weekly report, not a per-commit gate. Set a coverage target (e.g., 60% → 80% over two quarters).

### Ratchet integration changes

After each phase, update `ratchet_check.py` and `baseline.json`:

- Replace `xenon` with `C901`-per-code keys in `PROJECT_COUNTERS`, `DETAIL_COUNTERS`, and `DETAIL_PRINTERS`.
- Add new vector functions for `wily`, `vulture`, `bandit`, `deptry`, `pip-audit` (vulture/bandit as lint-level counts; wily as per-module maintainability/complexity counts; deptry/pip-audit as weekly checks outside the ratchet).
- Update `tool_totals` and `tool_baseline_totals` dictionaries.
- Preserve the existing staged-file detail check logic — the new tools should follow the same "block only if staged files introduce a new problem" contract.

Baseline migration for xenon → C901:

- Delete the `"xenon": 9` key from `baseline.json`.
- Run `ratchet_check.py` once with C901 enabled to bootstrap `ruff:C901` at its current count (10).
- Commit the new baseline in the same change that enables C901.

### Implementation phases

- Phase 1 (week 1): Enable `C90` + `RUF` subset + `ERA` in ruff. Migrate xenon → C901 in ratchet and baseline. Remove `radon`.
- Phase 2 (week 2): Add `wily` to ratchet. Bootstrap wily baselines.
- Phase 3 (week 3): Add `T10`, `ANN`, `N` to ruff. Update baseline.
- Phase 4 (week 4): Add `bandit` to pre-commit and ratchet.
- Phase 5 (month 2): Add `vulture` (non-blocking) and `deptry` (weekly). Add `pip-audit` (weekly).
- Phase 6 (month 3): Add `interrogate` coverage target. Re-evaluate `disallow_any_unimported` for mypy.

### Mutation-safety notes

- C901 vs radon: equivalent metric, different tool. Validate by comparing top-10 most-complex functions in both outputs before cutting over radon.
- Wily baseline bootstrap: run once, commit the output. No threshold logic — same self-pruning behavior as existing vectors.
- New ruff modules: each module should bootstrap at its project-wide count before becoming a blocking gate. Add to baseline.json with zero staged-file regression for the first commit.
- Bandit: start with `--exit-zero` (report only) for one week, then enable ratchet blocking once the initial count is known and triaged.

### Summary table

| tool-module | what it checks | rationale | block/warn | current state | planned | phase |
|---|---|---|---|---|---|---|
| xenon / radon cc | cyclomatic complexity per function | maintainability debt | Block | baseline: 9 | remove — replace with ruff C90 | Phase 1 |
| ruff / C90 (C901) | cyclomatic complexity per function | maintainability debt | Block | not enabled; 10 violations at default threshold | enable in ruff, remove radon | Phase 1 |
| wily / maintainability | maintainability index, Halstead volume, comment density | trend signal ruff cannot provide | Block | not in requirements | add to ratchet | Phase 2 |
| wily / complexity | cyclomatic complexity per module | cross-check for C901 scope differences | Block | not in requirements | add to ratchet | Phase 2 |
| ruff / RUF (RUF001–003, 005, 010, 012, 015, 100) | ambiguous unicode, mutable defaults, function calls in default args, inefficient unpacking, stale `noqa` | Python gotchas mypy does not flag | Block | not enabled | enable in ruff | Phase 1 |
| ruff / T10 (T100) | debugger breakpoints (`breakpoint()`, `pdb.set_trace()`) | broader than `debug-statements` hook | Block | not enabled; `debug-statements` hook exists | enable in ruff | Phase 3 |
| ruff / ERA (ERA001) | commented-out code | prevents `archive_not_used_trash` drift | Block | not enabled | enable in ruff | Phase 1 |
| ruff / ANN (ANN001, 002, 101, 102) | missing return/self/cls type annotations | complements mypy at lint level | Warn | not enabled | enable in ruff | Phase 3 |
| ruff / N (N802, 806, 812) | PEP 8 function/variable/import naming | consistency across 36 kLOC | Warn | not enabled | enable in ruff | Phase 3 |
| mypy / strict + disallow-any-explicit | type errors, explicit `Any` usage | type safety | Block | baseline: 90 errors | add `strict_equality`, `no_implicit_reexport` | Phase 6 |
| bandit / security patterns | hardcoded secrets, `eval`, `pickle`, weak crypto | in-code security risks | Block | not in requirements | add to pre-commit + ratchet | Phase 4 |
| vulture | unused code, dead imports, unused variables | dead-code triage | Warn | not in requirements | add as non-blocking hook | Phase 5 |
| deptry | unused dependencies in `requirements*.txt` / `pyproject.toml` | stale dependency removal | Warn | not in requirements | weekly check | Phase 5 |
| pip-audit | known CVEs in installed dependencies | dependency security | Warn | not in requirements | weekly check | Phase 5 |
| interrogate | docstring coverage percentage | documentation completeness | Warn | not in requirements | weekly report, target 80% | Phase 6 |
