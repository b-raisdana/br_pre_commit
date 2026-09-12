# br_pre_commit

Shared pre-commit infrastructure for python repositories. It owns the concurrent
wrapper, incremental ratchet, failure backup/recovery, hook installer, and their
tests. Projects keep only their own hook selection, optional overrides, and
project-specific ratchet baselines.

## Quick start

A checklist to get a new project running with `br_pre_commit`:

1. **Install `pre-commit`** in your Python environment (required before step 3):
   ```sh
   pip install pre-commit
   ```

2. **Clone `br_pre_commit` as a sibling** of your project:
   ```text
   code/
   ├── br_pre_commit/
   └── my_project/
   ```

3. **Create `my_project/.pre-commit-config.yaml`** — use
   [`br_pre_commit/.pre-commit-config.yaml`](.pre-commit-config.yaml) as your
   starting point. Only use **recognized hook IDs** (see the table below).

4. **Install the hook** from `my_project`:
   ```sh
   bash ../br_pre_commit/install.sh "$PWD"
   ```

5. **Verify** on a feature branch:
   ```sh
   git switch -c feature/initial-setup
   .git/hooks/pre-commit
   ```

See [Integrate into a new project](#integrate-into-a-new-project) below for
full details, and [Troubleshooting](#troubleshooting) if anything fails.

## Recognized hook IDs

**Every hook ID in your `.pre-commit-config.yaml` must be one of the IDs below.**
The wrapper classifies each ID against two fixed sets in
`src/br_pre_commit/precommit_config.py`. An ID not in either set is
"unregistered" and aborts the commit.

| Hook ID | Category | Description |
|---------|----------|-------------|
| `trailing-whitespace` | Mutating | Strips trailing whitespace |
| `end-of-file-fixer` | Mutating | Ensures files end with a newline |
| `mixed-line-ending` | Mutating | Normalizes line endings |
| `ruff` | Mutating | Runs `ruff check --fix` (formatter + linter) |
| `ruff-format` | Mutating | Runs `ruff format` |
| `sync-skill-files` | Mutating | Mirrors `SKILL.md` across agent dirs |
| `check-yaml` | Read-only | Validates YAML syntax |
| `check-toml` | Read-only | Validates TOML syntax |
| `check-added-large-files` | Read-only | Rejects large staged files |
| `check-merge-conflict` | Read-only | Detects unresolved conflict markers |
| `check-case-conflict` | Read-only | Detects case-insensitive filename clashes |
| `debug-statements` | Read-only | Blocks `breakpoint()` / `pdb` |
| `incremental-ratchet` | Read-only | Per-file regression gate (ratchet) |
| `pytest-fast` | Read-only | Runs unit tests with `pytest` |
| `pytest-integration-collect` | Read-only | Collects integration tests |
| `integration-tests` | Read-only | Runs integration tests |
| `check-pandera-decorator` | Read-only | Validates pandera decorators |
| `no-commit-to-main` | Read-only | Blocks direct commits to protected branches |

**Common mistakes:**

- Use `ruff`, not `ruff-check`.
- Use `pytest-fast`, not `pytest`.
- Use `check-yaml`, not `check-yaml-files` or `check_yaml`.

If you have a genuinely custom hook, set `wrapper.unknown-hook-policy = "warn"` in
`.br-pre-commit.toml` (see [project-settings.example.toml](project-settings.example.toml)).
This is a workaround, not a replacement for using registered IDs.

## Integrate into a new project

### Prerequisites

- Your project is a Git repository.
- `pre-commit` is installed in the Python environment used by Git hooks
  (`pip install pre-commit`).
- This `br_pre_commit` repository is available as a sibling directory:

```text
code/
├── br_pre_commit/
└── my_project/
```

If your project is a git submodule, the `br_pre_commit` repo should be checked
out as a sibling directory (not as a submodule of your project) — the wrapper
uses absolute paths recorded at install time.

### 1. Create `.pre-commit-config.yaml`

Hook selection remains project-owned. Copy the reference config and adjust:

```sh
cp ../br_pre_commit/.pre-commit-config.yaml .pre-commit-config.yaml
```

Then edit it: change entry commands, file patterns, and args to match your
project. Use only the **recognized hook IDs** listed above.

For a local incremental-ratchet hook, use:

```yaml
- repo: local
  hooks:
    - id: incremental-ratchet
      name: incremental ratchet
      language: system
      entry: ../br_pre_commit/ratchet
      pass_filenames: false
      files: ^src/.*\.py$
```

> **Note:** If your project uses `src/` instead of `app/`, set
> `target = "src"` in a `.br-pre-commit.toml` file (see
> [project-settings.example.toml](project-settings.example.toml)) so the
> ratchet and other tools find your code.

### 2. Install the hook

From your project directory:

```sh
bash ../br_pre_commit/install.sh "$PWD"
```

This writes a clone-local `.git/hooks/pre-commit` shim that records the
absolute paths of both your project and the `br_pre_commit` tool. Run it
directly to verify:

```sh
.git/hooks/pre-commit
```

On `main`, this verification intentionally fails (direct commits to `main` are
blocked). Create a feature branch first:

```sh
git switch -c feature/initial-setup
.git/hooks/pre-commit
```

### 3. Add a convenience launcher (optional)

```sh
cp ../br_pre_commit/pre-commit ./pre-commit
git add .pre-commit-config.yaml pre-commit
```

After that, `./pre-commit` and an ordinary `git commit` both use the shared
wrapper. Re-run `install.sh` after moving either checkout.

### Project-provided files

| File | Purpose |
|------|---------|
| `.pre-commit-config.yaml` | Enabled hooks and project-specific hook commands |
| `.br-pre-commit.toml` | Optional: overrides of shared defaults |
| `.br-pre-commit/ratchet/baseline_*.json` | Project's trend baselines (bootstrapped on first successful commit) |

See [project-settings.example.toml](project-settings.example.toml) for commented
override examples. Unspecified values inherit from
[defaults.toml](defaults.toml). The default protects `main`; set
`wrapper.protected-branches = []` only when a project deliberately permits direct
commits.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `configuration error: unregistered pre-commit hook(s): ...` | Hook ID not in the recognized table above | Rename to the correct ID (e.g. `ruff-check` → `ruff`, `pytest` → `pytest-fast`) |
| "No staged files" — hook skips entirely | Nothing is staged | `git add` your files first; the wrapper only runs on staged changes |
| Hook runs but finds no files | `files` pattern excludes your paths | Adjust the `files` regex or remove it for local hooks |
| Backup snapshot on every failure | Hook failed (expected during setup) | Read the report in `logs/pre-commit/pre-commit-runs/` |

See [docs/pre-commit-hook-id-diagnosis.md](docs/pre-commit-hook-id-diagnosis.md)
for a detailed walkthrough of the most common error.

## Recovery

On hook failure, snapshots are written inside the target project under
`logs/pre-commit/backup-patches/`. Restore one explicitly with:

```sh
python ../br_pre_commit/src/br_pre_commit/recover.py \
  --repo "$PWD" \
  --snapshot logs/pre-commit/backup-patches/<snapshot>
```

## Documentation

| Doc | What you'll find |
|-----|-----------------|
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Full design of the concurrent wrapper, branch protection, logging, advisory lint, and the backup/recovery pipeline. |
| [RATCHET.md](RATCHET.md) | Incremental pre-commit ratchet: per-file blocking gate, project-wide trend baselines, and the upgrade plan. |
| [SYNC_SKILLS.md](SYNC_SKILLS.md) | Bidirectional `SKILL.md` mirroring across agent directories (`.claude`, `.codex`, `.devin`, etc.) and conflict-resolution rules. |
| [defaults.toml](defaults.toml) | Shared default settings (`unknown-hook-policy`, `job-timeout-seconds`, `protected-branches`, ratchet parameters). |
| [project-settings.example.toml](project-settings.example.toml) | Commented template for a project-level `.br-pre-commit.toml` override file. |
| [docs/pre-commit-hook-id-diagnosis.md](docs/pre-commit-hook-id-diagnosis.md) | Troubleshooting guide for the "unregistered pre-commit hook(s)" error — root cause and fix. |
| [src/README.md](src/README.md) | Source-tree layout overview. |
| [src/br_pre_commit/README.md](src/br_pre_commit/README.md) | Module-level overview of the runtime package. |
| [src/br_pre_commit/incremental_precommit/README.md](src/br_pre_commit/incremental_precommit/README.md) | Ratchet module entry point and launcher reference. |
| [tests/README.md](tests/README.md) | How to run the test suite. |

## Development

```sh
bash install.sh "$PWD"
./pre-commit
python -m pytest -q
python -m py_compile src/br_pre_commit/*.py src/br_pre_commit/incremental_precommit/*.py
```

This repository uses the same shared wrapper it provides to sibling projects.
Its checked-in `.pre-commit-config.yaml` keeps `./pre-commit` usable in a fresh
clone after running the installer. Because this checkout normally remains on
`main`, its own hook is expected to stop at the shared branch guard until work
moves to a feature branch.
