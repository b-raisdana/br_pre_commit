# precommit_wrapper

Concurrent `pre-commit` runner installed as the target project's Git hook. Entry point: `python -m br_pre_commit.src.precommit_wrapper`, run from the target repository's root by the Git hook that `src/install.py` writes (no `PYTHONPATH` is exported). It runs the project's own configured hooks — it does not decide which checks exist.

## Modules

| Module | Responsibility |
| ------ | -------------- |
| `__main__.py` | Subprocess execution, one staged pre-commit pipeline, advisory lint jobs, backup trigger, process-group termination |
| `report.py` | Environment precondition check, branch protection, per-run report, JSON summary line, `main()` |
| `config.py` | Settings from `pyproject.toml` and the hook-ID classification sets |
| `hooks.py` | Which hook IDs the YAML enables (`stages` switch) |

## Settings

Read from `[tool.br_pre_commit.wrapper]` in the **user project's** `pyproject.toml` via `../helper/config.py` (no `.br-pre-commit.toml`, no per-project override file):

- `protected-branches-regex` — regex matched against the current branch name (default `^(main|develop|uat)$`).
- `unknown-hook-policy` — `warn` (default) or `error`: what happens to hook IDs the wrapper cannot classify.
- `job-timeout-seconds` — per-hook timeout, default `180`.

## Hook execution

- The wrapper launches one `pre-commit run --hook-stage pre-commit --color never --files <staged>` process. Pre-commit runs configured hooks in YAML order and manages staged-file isolation once.
- The wrapper runs advisory Ruff and Radon checks alongside that process for staged Python files; advisory findings do not block commits.
- With no staged files, the wrapper runs one full `pre-commit run --hook-stage pre-commit` and skips advisory lint.
- Do not wrap nested pre-commit commands in `staged_files_only`; it makes the staged changes appear unstaged to the child process and triggers the hook-modified-files failure.
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
