# br_pre_commit

Shared pre-commit infrastructure for python repositories. It owns the concurrent wrapper, incremental ratchet, failure backup/recovery, hook installer, and their tests. Projects keep only their own hook selection, optional overrides, and project-specific ratchet baselines.

## Table of Contents

- [br_pre_commit](#br_pre_commit)
  - [Table of Contents](#table-of-contents)
  - [Quick start](#quick-start)
  - [Recognized hook IDs](#recognized-hook-ids)
  - [Standard hooks](#standard-hooks)
  - [Specialized hooks](#specialized-hooks)
  - [Other kind if integration](#other-kind-if-integration)
    - [After cloning a consuming project...](#after-cloning-a-consuming-project)
    - [To upgrade deliberately the 'br_pre_commit' to a new version](#to-upgrade-deliberately-the-br_pre_commit-to-a-new-version)
    - [Complete integration checklist](#complete-integration-checklist)
  - [Troubleshooting](#troubleshooting)
  - [Recovery](#recovery)
  - [Documentation](#documentation)
  - [Development](#development)

## Quick start

A checklist to get a new project running with `br_pre_commit`:

1. **Install `pre-commit`** in your Python environment (required before step 3):

   ```sh
   pip install pre-commit
   ```

2. **Add `br_pre_commit` as a git submodule** in your project:

   ```text
   your_project_root/
   ├── .git/
   ├── .gitmodules
   ├── br_pre_commit/     <-- git submodule
   └── ...your project files...
   ```

   ```sh
   git submodule add git@github.com:b-raisdana/br_pre_commit.git br_pre_commit
   git submodule update --init --recursive
   ```

3. **Install the hook** from `your_project`:

   ```sh
   bash ./br_pre_commit/install/install.sh "$PWD"
   ```

   or

   ```pwsh
   ./br_pre_commit/install/install.ps1 "$PWD"
   ```

   This writes `git hook run pre-commit` that records the absolute paths of both your project and the `br_pre_commit` tool. Run it directly to verify:

   ```sh
   git hook run pre-commit
   ```

   On `main`, the `no-commit-to-main` verification intentionally fails (direct commits to `main` are
   blocked). Create a feature branch first:

   ```sh
   git switch -c feature/initial-setup
   git hook run pre-commit
   ```

   After any successful or even a failing commit to any branch including 'main' (which shall be prevented / fail), the 'logs/pre-commit' should be create and have these sub-folders:
   - backup-patches/: Backups git patched can be used specifically to track every single modification done in a git per-branch basis.
   - full_backup/: Backups the text-based files completely. Keeps different complete versions of all of files distinguished by their short-hash embedded in files name. 'full_backup_exclude_dir_regex' in 'pyproject.toml' can be used to exclude files.
   - pre-commit-runs/: Per run dedicated logs
   - pre-commit.log: Incrementally appended logs in a single file.

4. **Customize**:

   Install.py which is the core of installer, merges defualt .pre-commit-config.yaml and pyproject.toml files into existing files in the user-repo

   Only use **recognized hook IDs** (see the table below).
   **there are 2 config files**:
   - `your_project/.pre-commit-config.yaml`
   - `your_project/pyproject.toml`

5. **Verify** on a feature branch (not `main`):

   ```sh
   git switch -c feature/initial-setup
   git hook run pre-commit
   ```

6. **Bootstrap ratchet baselines** (first successful commit):
   The incremental ratchet creates `baseline_*.json` in `.br-pre-commit/ratchet/` automatically on the first passing commit.

See [Integrate into a new project](#integrate-into-a-new-project) below for full details, and [Troubleshooting](#troubleshooting) if anything fails.

## Recognized hook IDs

**Every hook ID in your `.pre-commit-config.yaml` must be one of the IDs below.**
The wrapper classifies each ID against two fixed sets in `src/precommit_wrapper/config.py`. An ID not in either set is "unregistered" and aborts the commit.

## Standard hooks

| Hook ID                      | Category  | Description                                  |
| ---------------------------- | --------- | -------------------------------------------- |
| `trailing-whitespace`        | Mutating  | Strips trailing whitespace                   |
| `end-of-file-fixer`          | Mutating  | Ensures files end with a newline             |
| `mixed-line-ending`          | Mutating  | Normalizes line endings                      |
| `ruff`                       | Mutating  | Runs `ruff check --fix` (formatter + linter) |
| `ruff-format`                | Mutating  | Runs `ruff format`                           |
| `check-yaml`                 | Read-only | Validates YAML syntax                        |
| `check-toml`                 | Read-only | Validates TOML syntax                        |
| `check-added-large-files`    | Read-only | Rejects large staged files                   |
| `check-merge-conflict`       | Read-only | Detects unresolved conflict markers          |
| `check-case-conflict`        | Read-only | Detects case-insensitive filename clashes    |
| `debug-statements`           | Read-only | Blocks `breakpoint()` / `pdb`                |
| `pytest-fast`                | Read-only | Runs unit tests with `pytest`                |
| `pytest-integration-collect` | Read-only | Collects integration tests                   |
| `integration-tests`          | Read-only | Runs integration tests                       |

## Specialized hooks

| Hook ID                   | Category  | Description                                  |
| ------------------------- | --------- | -------------------------------------------- |
| `sync-skill-files`        | Mutating  | Mirrors `SKILL.md` across agent dirs         |
| `incremental-ratchet`     | Read-only | Per-file regression gate (ratchet)           |
| `check-pandera-decorator` | Read-only | Validates pandera decorators                 |
| `no-commit-to-main`       | Read-only | Blocks direct commits to protected branches  |
| `no-object-annotations`   | Read-only | Blocks generic 'object' type in type-hinting |

## Other kind if integration

### After cloning a consuming project...

### To upgrade deliberately the 'br_pre_commit' to a new version

### Complete integration checklist

After the quick start, verify these features are configured for your project:

- [ ] **Core hygiene hooks** (from `pre-commit-hooks`): `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-toml`, `check-added-large-files`, `check-merge-conflict`, `check-case-conflict`, `debug-statements`, `mixed-line-ending`
- [ ] **Ruff lint + format**: `ruff` (with `--fix`), `ruff-format`
- [ ] **Type checking**: `mypy` (strict mode) — add to `.pre-commit-config.yaml` as a local hook
- [ ] **Complexity**: `incremental-ratchet` (replaces `xenon`/`radon`; uses ruff `C901`)
- [ ] **Unit tests**: `pytest-fast` (runs `pytest -q -m unit`)
- [ ] **Integration tests**: `pytest-integration-collect` + `integration-tests` (if applicable)
- [ ] **Pandera validation**: `check-pandera-decorator` (if using pandera)
- [ ] **Branch protection**: `no-commit-to-main` (built into wrapper via `protected-branches`)
- [ ] **Security scanning**: `detect-secrets` or `gitleaks` (add as blocking hook)
- [ ] **Dependency audit**: `pip-audit` (weekly, block on high/critical CVEs)
- [ ] **In-code security**: `bandit` (ratchet-tracked, start with `--exit-zero`)
- [ ] **Dead code detection**: `vulture` (non-blocking warnings)
- [ ] **Unused dependencies**: `deptry` (weekly report)
- [ ] **Docstring coverage**: `interrogate` (weekly, target 80%)
- [ ] **Skill file sync**: `sync-skill-files` (if using shared skills across agents)

See [IMPLEMENTATION.md](IMPLEMENTATION.md) § "Pre-commit gap analysis" for the full
priority-ordered roadmap (P0–P3).

## Troubleshooting

| Symptom                                                     | Likely cause                              | Fix                                                                             |
| ----------------------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------- |
| `configuration error: unregistered pre-commit hook(s): ...` | Hook ID not in the recognized table above | Rename to the correct ID (e.g. `ruff-check` → `ruff`, `pytest` → `pytest-fast`) |
| "No staged files" — hook skips entirely                     | Nothing is staged                         | `git add` your files first; the wrapper only runs on staged changes             |
| Hook runs but finds no files                                | `files` pattern excludes your paths       | Adjust the `files` regex or remove it for local hooks                           |
| Backup snapshot on every failure                            | Hook failed (expected during setup)       | Read the report in `logs/pre-commit/pre-commit-runs/`                           |

See [docs/pre-commit-hook-id-diagnosis.md](docs/pre-commit-hook-id-diagnosis.md)
for a detailed walkthrough of the most common error.

## Recovery

On hook failure, snapshots are written inside the target project under
`logs/pre-commit/backup-patches/`. Restore one explicitly with:

```sh
python -m src.backup.recover \
  --repo "$PWD" \
  --snapshot logs/pre-commit/backup-patches/<snapshot>
```

## Documentation

| Doc                                                                                                                    | What you'll find                                                                                                                                                    |
| ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [IMPLEMENTATION.md](IMPLEMENTATION.md)                                                                                 | Full design of the concurrent wrapper, branch protection, logging, advisory lint, and the backup/recovery pipeline.                                                 |
| [RATCHET.md](RATCHET.md)                                                                                               | Incremental pre-commit ratchet: per-file blocking gate, project-wide trend baselines, and the upgrade plan.                                                         |
| [src/sync_skills/README.md](src/sync_skills/README.md)                                                                 | Bidirectional `SKILL.md` mirroring across agent directories (`.claude`, `.codex`, `.devin`, etc.) and conflict-resolution rules.                                    |
| [pyproject.toml](pyproject.toml)                                                                                       | Shared default settings under `[tool.br_pre_commit.*]` (`unknown-hook-policy`, `job-timeout-seconds`, `protected-branches`, ratchet parameters, backup exclusions). |
| [docs/pre-commit-hook-id-diagnosis.md](docs/pre-commit-hook-id-diagnosis.md)                                           | Troubleshooting guide for the "unregistered pre-commit hook(s)" error — root cause and fix.                                                                         |
| [docs/development/cross-environment-installation-design.md](docs/development/cross-environment-installation-design.md) | Linux, WSL, and Windows installation modes, Python/toolchain assumptions, and cross-environment commit policy.                                                      |
| [src/README.md](src/README.md)                                                                                         | Source-tree layout overview.                                                                                                                                        |
| [src/ratchet/README.md](src/ratchet/README.md)                                                                         | Ratchet module entry point and launcher reference.                                                                                                                  |
| [tests/README.md](tests/README.md)                                                                                     | How to run the test suite.                                                                                                                                          |

## Development

```sh
bash install/install.sh "$PWD"
./pre-commit
python -m pytest -q
python -m py_compile src/*.py src/ratchet/*.py
```

This repository uses the same shared wrapper it provides to projects using it as a submodule.
Its checked-in `.pre-commit-config.yaml` keeps `./pre-commit` usable in a fresh
clone after running the installer. Because this checkout normally remains on
`main`, its own hook is expected to stop at the shared branch guard until work
moves to a feature branch.
