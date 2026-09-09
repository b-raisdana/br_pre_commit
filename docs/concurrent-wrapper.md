# Concurrent pre-commit wrapper

`src/br_pre_commit/precommit_wrapper.py` is the shared entry point that every
installed Git hook delegates to. It reads a consumer project's
`.pre-commit-config.yaml`, classifies the enabled hooks, runs them with a
mix of serial and concurrent scheduling, protects branches, logs results,
and triggers a failure backup when something goes wrong.

The wrapper itself performs **no quality checks** — it is a scheduler and
observer. The hooks it runs are the ones the consumer project selects.

## Invocation

The installed `.git/hooks/pre-commit` shim calls the `run` launcher, which
executes:

```
python src/br_pre_commit/precommit_wrapper.py [extra pre-commit args...]
```

See [hook-installer.md](hook-installer.md) for how the shim is written and
how it resolves the tool checkout vs. the target project checkout.

## Branch protection

Before any hook runs, the wrapper resolves the current branch through
`git rev-parse --abbrev-ref HEAD` and checks it against
`wrapper.protected-branches` (loaded from `defaults.toml` with optional
`.br-pre-commit.toml` overrides; `["main"]` by default). A commit to a
protected branch short-circuits the whole pipeline and fails immediately.
List additional protected branch names, or set the list to `[]` when a
project deliberately permits direct commits.

## Hook classification

`precommit_config.py` classifies each enabled hook id into one of three buckets:

| Bucket | Hooks | Scheduling |
|---|---|---|
| **Mutating** | `trailing-whitespace`, `end-of-file-fixer`, `mixed-line-ending`, `ruff`, `ruff-format`, `sync-skill-files` | Run **serially, in declaration order**. They rewrite files, so concurrent mutation would collide. |
| **Read-only** | `check-yaml`, `check-toml`, `check-added-large-files`, `check-merge-conflict`, `check-case-conflict`, `debug-statements`, `incremental-ratchet`, `pytest-fast`, `pytest-integration-collect`, `integration-tests`, `check-pandera-decorator`, `no-commit-to-main` | Run **concurrently** as subprocesses. |
| **Unknown** | Any id not in either set | Controlled by `wrapper.unknown-hook-policy`: `error` (default) raises and aborts; `warn` runs it serially with a warning. |

Only hooks in the `pre-commit` stage are scheduled — a hook tagged
`stages: [pre-push]` is ignored here.

## Concurrency model

The wrapper uses `asyncio` with one terminal lock so live output from
concurrent jobs stays line-ordered:

- Each job is launched with `start_new_session=True` so it owns its own
  process group, which lets the wrapper terminate the whole group on timeout.
- stdout/stderr are read continuously into per-job in-memory buffers and, while
  streaming, prefixed with `[<job-id>:<stream>]`. Non-streaming jobs (e.g. the
  advisory ruff check) buffer silently and only emit via the report.
- A job that exceeds `wrapper.job-timeout-seconds` (default `900`) is sent
  `SIGTERM` to its process group, then `SIGKILL` after a 3-second grace.
  The job is recorded with return code `124`.

Mutating hooks are awaited **before** the read-only jobs are scheduled, so
formatting/fixing hooks always finish before read-only checks (linters,
tests) see the rewritten files.

## Staged-files context

When files are staged, the wrapper passes them explicitly to each hook via
`--files`, and wraps the run in `pre_commit.staged_files_only` so the index
is never disturbed by the hook's own stashing. If nothing is staged, it falls
back to a plain `pre-commit run` over the whole repo.

## Advisory lint warnings

`Q`, `RUF`, `T10`, `T20`, and `ERA` rules are deliberately **excluded** from
the consumer project's `pyproject.toml` `[tool.ruff.lint] select` so they do
not produce editor squiggles or gate the ratchet. Instead, the wrapper runs
these rules as a non-blocking, concurrent `ruff check` over staged `app/*.py`
files (streaming disabled, output parsed as JSON). Any violations are surfaced
as `warning:` lines on stdout and also recorded in the log entry under
`advisory_lint_warnings` — never blocking.

## Logging

After every job finishes, the wrapper writes two artifacts under
`logs/pre-commit/`:

- `pre-commit-runs/<human-timestamp>.log` — an ordered, per-job report: status,
  exit code, duration, command, full stdout, and full stderr.
- `pre-commit.log` — a JSON-line summary appended on every run, with the
  timestamp, branch, staged files, overall result, per-job exit codes,
  advisory warnings, the report path, and (on failure) the snapshot path.

Per-job stdout/stderr live in RAM buffers for the run; the timestamped report
is written atomically (temp file + `replace`).

## Failure backup

When any blocking job fails (return code != 0), the wrapper runs
`backup.py` in a dedicated subprocess (see
[failure-backup-recovery.md](failure-backup-recovery.md)) and records the
snapshot directory in both stdout and the JSON summary. The snapshot is the
only thing standing between a failed hook and lost staged work.

## Exit behavior

The wrapper returns `1` if any blocking job failed (or branch protection
triggered), `0` otherwise. `SIGINT` raises `KeyboardInterrupt`, which is logged
and mapped to exit code `1`.
