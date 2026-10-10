# br_pre_commit

Shared pre-commit infrastructure for python repositories. It owns the concurrent wrapper, incremental ratchet, failure backup/recovery, hook installer, and their tests. Projects keep only their own hook selection, optional overrides, and project-specific ratchet baselines.

## Table of Contents

- [br\_pre\_commit](#br_pre_commit)
  - [Table of Contents](#table-of-contents)
  - [Quick start](#quick-start)
  - [Recognized hook IDs](#recognized-hook-ids)
    - [Enabling / disabling each control](#enabling--disabling-each-control)
  - [Backup exclusion regex](#backup-exclusion-regex)
  - [Standard hooks](#standard-hooks)
  - [Specialized hooks](#specialized-hooks)
    - [`no-object-annotations`](#no-object-annotations)
    - [`incremental-ratchet` — when and how to run a baseline](#incremental-ratchet--when-and-how-to-run-a-baseline)
  - [Other kind if integration](#other-kind-if-integration)
    - [After cloning a consuming project...](#after-cloning-a-consuming-project)
    - [To upgrade deliberately the 'br\_pre\_commit' to a new version](#to-upgrade-deliberately-the-br_pre_commit-to-a-new-version)
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

   On `main`, the `no-commit-to-trunk` verification intentionally fails (direct commits to `main` are
   blocked). Create a feature branch first:

   ```sh
   git switch -c feature/initial-setup
   git hook run pre-commit
   ```

After any successful or even a failing commit to any branch including 'main' (which shall be prevented / fail), the 'logs/pre-commit' should be create and have these sub-folders:
- backup-patches/: Backups git patched can be used specifically to track every single modification done in a git per-branch basis.
- full_backup/: Backups the text-based files completely. Keeps different complete versions of all of files distinguished by their short-hash embedded in files name. Files are excluded from full backup via `full_backup_exclude_dir_regex` in `pyproject.toml` (see [Backup exclusion regex](#backup-exclusion-regex) below).
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

The checked-in `.pre-commit-config.yaml` is the master functionality list. Every hook below has an explicit native pre-commit switch: set `stages: [pre-commit]` to enable it for commits or `stages: [manual]` to disable it while retaining its complete configuration. The wrapper, including its early protected-branch check, follows these switches. A manually disabled hook can still be run explicitly with `pre-commit run <hook-id> --hook-stage manual`.

### Enabling / disabling each control

Each hook is controlled entirely by its `stages` entry in your project's
`.pre-commit-config.yaml`. The wrapper reads this file and only runs hooks whose
`stages` include `pre-commit`. There is no separate toggle for the specialized
hooks — the YAML is the single switch.

**Enable a hook** (the default for every hook shown above):

```yaml
- id: no-object-annotations
  name: block object type annotations
  language: system
  entry: python -m src.check_no_object_annotations
  pass_filenames: true
  stages:
    - pre-commit
```

**Disable a hook** while keeping its configuration in place (it will not run
during commits, but you can still invoke it manually):

```yaml
- id: no-object-annotations
  name: block object type annotations
  language: system
  entry: python -m src.check_no_object_annotations
  pass_filenames: true
  stages:
    - manual
```

**Re-enable** by changing `manual` back to `pre-commit`. The hook is fully
configured either way — only its *participation in the commit pipeline* changes.

Per-hook knobs that are not the on/off switch live in `pyproject.toml` under
`[tool.br_pre_commit.*]`:

| Section | Controls |
| ------- | -------- |
| `[tool.br_pre_commit.wrapper]` | `protected-branches-regex`, `unknown-hook-policy`, `job-timeout-seconds` |
| `[tool.br_pre_commit.ratchet]` | `target`, `max-lines`, `line-growth-slack`, `complexity-ranks`, `xenon-max-absolute`, `exclude-dir` |
| `[tool.br_pre_commit.backup]` | `full_backup_exclude_dir_regex` |
| `[tool.br_pre_commit.sync_skills]` | `hardcoded-skips` |

See [pyproject.toml](pyproject.toml) for the shared defaults a consuming
project inherits.

## Backup exclusion regex

The backup system takes two kinds of snapshots on every pre-commit run:

- **Patch backups** (`logs/pre-commit/backup-patches/`) — git diffs for each
  tracked file that changed in the commit. Only modified tracked files appear here.
- **Full backups** (`logs/pre-commit/full_backup/`) — complete copies of text-based
  files (tracked, unstaged, and untracked) that are **not excluded** by the
  `full_backup_exclude_dir_regex` regex. Excluded files are **not backed up at all**
  (no patch, no full copy).

The regex is defined in `pyproject.toml` under `[tool.br_pre_commit.backup]`:

```toml
[tool.br_pre_commit.backup]
full_backup_exclude_dir_regex = '^(data|logs|archive_not_used_trash|\.[^/]+)$'
```

### How it works

The regex is matched against **each individual path part** (directory or filename)
in the file's relative path. A file is excluded from full backup if **any** path
part fully matches the regex.

The default regex breaks down as:

| Pattern | Matches |
|---------|---------|
| `data` | Any directory named `data` at any depth |
| `logs` | Any directory named `logs` at any depth |
| `archive_not_used_trash` | Any directory with this exact name |
| `\.[^/]+` | Any hidden directory (starts with `.`, e.g. `.git`, `.venv`, `.mypy_cache`) |

### Customizing the regex

To add or remove directories from full backup exclusion, edit the regex in your
project's `pyproject.toml`. The regex must be a valid Python regex pattern.

**Example: also exclude a `tmp` directory and `.pytest_cache`:**

```toml
[tool.br_pre_commit.backup]
full_backup_exclude_dir_regex = '^(data|logs|archive_not_used_trash|tmp|\.[^/]+)$'
```

**Example: allow `logs` to be fully backed up (remove it from exclusion):**

```toml
[tool.br_pre_commit.backup]
full_backup_exclude_dir_regex = '^(data|archive_not_used_trash|\.[^/]+)$'
```

### What gets backed up vs. excluded

| File path | Excluded? | Reason |
|-----------|-----------|--------|
| `src/main.py` | No | No path part matches |
| `data/large.csv` | Yes | `data` matches |
| `logs/app.log` | Yes | `logs` matches |
| `.venv/lib/...` | Yes | `.venv` matches `\.[^/]+` |
| `src/.hidden/file.py` | No | Only `.hidden` would match, not `src` or `file.py` |

> **Note:** Patch backups (`backup-patches/`) are not affected by this regex —
 > they always capture diffs for any tracked file that changed, regardless of its
 > path. The regex only controls which files get a **full copy** in `full_backup/`.

### Per-attempt manifest

Every backup attempt also writes a JSON manifest under
`logs/pre-commit/backup-manifests/`, named after the human-readable timestamp
(with milliseconds) of the attempt, e.g. `2026-10-09T14-21-15.167.json`.
It lists the absolute full path of every backup file produced by that attempt —
staged patches, unstaged patches, untracked copies, and full backups — so the
files belonging to a single pre-commit/backup run can be located and restored
together without scanning the whole `logs/pre-commit/` tree.

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

| Hook ID                   | Category  | Description                                  | Docs |
| ------------------------- | --------- | -------------------------------------------- | ---- |
| `sync-skill-files`        | Mutating  | Mirrors `SKILL.md` across agent dirs         | [sync_skills/README.md](src/sync_skills/README.md) |
| `incremental-ratchet`     | Read-only | Per-file regression gate (ratchet)           | [ratchet/README.md](src/ratchet/README.md) + [RATCHET.md](src/ratchet/RATCHET.md) |
| `check-pandera-decorator` | Read-only | Validates pandera decorators                 | [br_pandera/README.md](src/br_pandera/README.md#companion-hook) |
| `no-commit-to-trunk`     | Read-only | Blocks direct commits to protected branches  | [precommit_wrapper/README.md](src/precommit_wrapper/README.md#branch-protection) |
| `no-object-annotations`   | Read-only | Blocks generic 'object' type in type-hinting | [check_no_object_annotations.md](src/check_no_object_annotations.md) |

### `no-object-annotations`

The hook rejects an explicit `object` annotation anywhere in a type hint (parameter, return, variable) and suggests a more specific type.

To allow one, add the ignore tag as a comment inside the annotation, on the same line as the `object` occurrence:

```python
def read_section(section: str) -> dict[str, object]:  # ignore: no-object-annotations
    ...
```

The tag must match exactly `# ignore: no-object-annotations`. Because it is matched against the annotation's own source lines, a multi-line annotation needs the tag on the line holding `object`; a tag on the `def` line above it does not suppress anything. A `cast("dict[str, object]", value)` inside the function body is not an annotation, so it needs no tag.

### `incremental-ratchet` — when and how to run a baseline

The ratchet has two layers: a **per-file blocking gate** (recomputed fresh on every commit, nothing to bootstrap) and a **project-wide trend baseline** (`baseline*.json` in `.br-pre-commit/ratchet/`, content-addressed by SHA-256). Only the trend layer needs a baseline.

#### When to run a baseline

- **First setup / fresh clone** — the first passing commit bootstraps the baseline automatically (see step 6 of [Quick start](#quick-start)).
- **After a deliberate mass cleanup** (many files fixed at once) — re-baseline so the new lower count becomes the floor, otherwise the next commit will look like a regression.
- **When a key's meaning changes** (e.g. a tool's scope or a configured threshold is edited) — delete the stale key from every `baseline*.json` and re-baseline, otherwise the old and new counts are compared against each other.
- **To reset everything** — delete all `baseline*.json` files and re-baseline from scratch.

#### How to run a baseline

The baseline is produced by the same ratchet entry point the hook uses, run manually (outside of a commit it just measures and writes, it does not block):

```sh
# from the consuming project's root
python -m br_pre_commit.src.ratchet
```

Or, equivalently, make a passing commit on a feature branch — the hook runs the same code and writes `baseline_<hash>.json` automatically.

For a targeted re-baseline of a single key, delete that key from the existing baseline file(s) and run the command above once; the key is re-measured and recorded at its current count:

```sh
# example: drop the xenon key, then re-measure
python - <<'PY'
import json, glob
for p in glob.glob(".br-pre-commit/ratchet/baseline*.json"):
    data = json.loads(open(p).read())
    data.pop("xenon", None)
    open(p, "w").write(json.dumps(data, indent=2, sort_keys=True) + "\n")
PY
python -m br_pre_commit.src.ratchet
```

The trend layer **never blocks** — it only signals whether total debt is going up or down. The blocking gate is always the per-file before/after diff. See [src/ratchet/README.md](src/ratchet/README.md) and [src/ratchet/RATCHET.md](src/ratchet/RATCHET.md) for the full design.

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
- [ ] **Branch protection**: `no-commit-to-trunk` (built into wrapper via `protected-branches-regex`)
- [ ] **Security scanning**: `detect-secrets` or `gitleaks` (add as blocking hook)
- [ ] **Dependency audit**: `pip-audit` (weekly, block on high/critical CVEs)
- [ ] **In-code security**: `bandit` (ratchet-tracked, start with `--exit-zero`)
- [ ] **Dead code detection**: `vulture` (non-blocking warnings)
- [ ] **Unused dependencies**: `deptry` (weekly report)
- [ ] **Docstring coverage**: `interrogate` (weekly, target 80%)
- [ ] **Skill file sync**: `sync-skill-files` (if using shared skills across agents)

See [src/README.md](src/README.md) for the runtime layout behind these hook IDs, and [docs/change-log](docs/change-log) for the delivery history behind this checklist.

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
| [src/README.md](src/README.md)                                                                                         | Source-tree layout overview, with links to every package README.                                                                                                     |
| [src/precommit_wrapper/README.md](src/precommit_wrapper/README.md)                                                       | Concurrent wrapper internals: module map, hook classification, scheduling, exit codes, log/summary formats, and the deliberate `__main__`/`report.py` circular import. |
| [src/br_pandera/README.md](src/br_pandera/README.md)                                                                           | `pandera_validate` decorator options, call-time kwargs, NaN-fill detection, dump-folder rules, and the package-qualified import surface.                                 |
| [src/ratchet/README.md](src/ratchet/README.md)                                                                         | Ratchet module entry point, layering, and module-grouping rationale.                                                                                               |
| [src/ratchet/RATCHET.md](src/ratchet/RATCHET.md)                                                                       | Incremental ratchet design: per-file blocking gate, project-wide trend baselines, upgrade plan.                                                                   |
| [src/sync_skills/README.md](src/sync_skills/README.md)                                                                 | Bidirectional `SKILL.md` mirroring across agent directories (`.claude`, `.codex`, `.devin`, etc.) and conflict-resolution rules.                                    |
| [src/backup/README.md](src/backup/README.md)                                                                           | Backup system: patch/full snapshots, exclusion regex, content-addressed storage, recovery commands.                                                                 |
| [src/check_no_object_annotations.md](src/check_no_object_annotations.md)                                               | `no-object-annotations` hook: ignore tag mechanism (`# ignore: no-object-annotations`), multi-line handling, cast exclusion.                                        |
| [pyproject.toml](pyproject.toml)                                                                                       | Shared default settings under `[tool.br_pre_commit.*]` (`unknown-hook-policy`, `job-timeout-seconds`, `protected-branches-regex`, ratchet parameters, backup exclusions, sync_skills). |
| [docs/pre-commit-hook-id-diagnosis.md](docs/pre-commit-hook-id-diagnosis.md)                                           | Troubleshooting guide for the "unregistered pre-commit hook(s)" error — root cause and fix.                                                                         |
| [docs/development/cross-environment-installation-design.md](docs/development/cross-environment-installation-design.md) | Linux, WSL, and Windows installation modes, Python/toolchain assumptions, and cross-environment commit policy.                                                      |
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
