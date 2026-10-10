# precommit_wrapper

Concurrent `pre-commit` runner installed as the target project's Git hook. Entry point: `python -m br_pre_commit.src.precommit_wrapper`, run from the target repository's root by the Git hook that `src/install.py` writes (no `PYTHONPATH` is exported). It runs the project's own configured hooks — it does not decide which checks exist.

## Modules

| Module | Responsibility |
| ------ | -------------- |
| `__main__.py` | Subprocess execution, mutating-serial then read-only-concurrent scheduling, advisory lint jobs, backup trigger, process-group termination |
| `report.py` | Environment precondition check, branch protection, per-run report, JSON summary line, `main()` |
| `config.py` | Settings from `pyproject.toml` and the hook-ID classification sets |
| `hooks.py` | Which hook IDs the YAML enables (`stages` switch) |

## Settings

Read from `[tool.br_pre_commit.wrapper]` in the **user project's** `pyproject.toml` via `../helper/config.py` (no `.br-pre-commit.toml`, no per-project override file):

- `protected-branches-regex` — regex matched against the current branch name (default `^(main|develop|uat)$`).
- `unknown-hook-policy` — `warn` (default) or `error`: what happens to hook IDs the wrapper cannot classify.
- `job-timeout-seconds` — per-hook timeout, default `180`.

## Hook classification

Each enabled ID falls in exactly one set:

- **Mutating** (`get_mutating_hooks()`) — run serially, in YAML order, before anything else, because they rewrite files (`trailing-whitespace`, `end-of-file-fixer`, `mixed-line-ending`, `ruff`, `ruff-format`, `sync-skill-files`, `incremental-ratchet`).
- **Read-only** (`_READ_ONLY_HOOKS`) — all launched concurrently.

IDs in neither set are "unregistered": under `policy="error"` `classify_hooks()` raises `unregistered pre-commit hook(s): <ids>`; under `policy="warn"` they run serially and the wrapper prints `warning: unregistered hooks run serially: <ids>`. The root `README.md` § "Recognized hook IDs" lists the full sets, and `.pre-commit-config.yaml` is the authoritative reference config.

## Execution model

- Every hook runs as `pre-commit run <id> --hook-stage pre-commit --color never --files <staged>`, with cwd = the user repo.
- Concurrent hooks additionally run alongside two **advisory** jobs on staged `src/**/*.py`: `advisory-ruff` (`--select Q,RUF,T10,T20,ERA`, JSON) and `advisory-radon` (`mi --min B --max C`). Their stdout is not streamed; findings are parsed by `report.py` into the summary as `advisory_lint_warnings` and printed as `warning:` lines.
- Advisory jobs **never fail the commit** — `report.py` excludes any job whose ID starts with `advisory-` when computing `passed`.
- With no staged files the wrapper falls back to one full `pre-commit run --hook-stage pre-commit` and skips the staged-files-only sandbox.
- Hooks run inside `pre_commit.staged_files_only(Store().directory)` so mutating hooks see only the staged tree.

## Branch protection

When `no-commit-to-trunk` is enabled, `report.py` calls `_branch_protection_result()` **before** the pipeline. On a protected branch with no merge in progress (`git rev-parse --verify MERGE_HEAD` fails), it returns a synthetic failing job: no hook runs, no backup is taken, the commit aborts. The merge-progress check lets merge commits through.

## Failure handling and exit codes

| Code | Meaning |
| ---- | ------- |
| `0` | all blocking jobs passed |
| `1` | at least one blocking hook failed, or `KeyboardInterrupt` |
| `2` | configuration error (e.g. unregistered IDs under `policy="error"`) |
| `3` | `requirements.txt` unsatisfied — the run stops *before any hook starts* |
| `124` | hook exceeded `job-timeout-seconds`; its process group is SIGTERM then SIGKILL |
| `127` | hook could not be started (`OSError`) |

On any blocking failure the wrapper then runs `python -m br_pre_commit.src.backup --repo <user repo>` and records the snapshot path in the summary. Timeout handling kills the whole process group (`killpg` on POSIX, `terminate`/`kill` on Windows) so hooks that spawn children cannot outlive the run.

## Outputs

- `logs/pre-commit/pre-commit-runs/<YYYY-mm-dd_HH-MM-SS_ffffff>.log` — per-hook status, exit code, duration, command, full stdout/stderr.
- `logs/pre-commit/pre-commit.log` — one JSON `SummaryEntry` per run appended as a single line: timestamp, branch, staged files, pass/fail, per-job exit codes, advisory warnings, report path, snapshot dir.

## Import boundary (deliberate circular import)

`__main__.py` and `report.py` depend on each other by design: `__main__.py` imports `report.main` at the bottom of the module, and `report.py` imports `JobResult`, `_run_hooks`, `_run_job`, `_run_backup`, and `log` **inside function bodies**, with `JobResult` additionally imported under `TYPE_CHECKING` for annotations. Any module-level import in `report.py` would be a circular-import failure at runtime. New cross-module symbols must follow the same rule.

## Known duplication

`hooks.py` still carries its own `HookSpec`, `_READ_ONLY_HOOKS`, and `classify_hooks` that duplicate `config.py`. Only `enabled_pre_commit_hook_ids()` and `pre_commit_hook_is_enabled()` from `hooks.py` are used (`__main__.py`, `report.py`, `../ratchet/gate.py`); the duplicated trio is dead and can be deleted without touching callers.
