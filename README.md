# br_pre_commit

Shared pre-commit infrastructure for python repositories. It owns the concurrent
wrapper, incremental ratchet, failure backup/recovery, hook installer, and their
tests. Projects keep only their own hook selection, optional overrides, and
project-specific ratchet baselines.

## Documentation

- **[Concurrent wrapper](docs/concurrent-wrapper.md)** — how enabled hooks are
  classified and scheduled (mutating hooks serially, read-only hooks
  concurrently), branch protection, timeouts, live logging, and advisory lint
  warnings.
- **[Incremental ratchet](docs/incremental-ratchet.md)** — the per-touched-file
  regression gate and the project-wide trend baseline that ratchets debt down.
- **[Failure backup & recovery](docs/failure-backup-recovery.md)** — the read-only
  snapshot taken on hook failure and how to restore working state with
  `recover.py`.
- **[Hook installer](docs/hook-installer.md)** — `install.sh`, the
  `.git/hooks/pre-commit` shim, WSL handling, and the `run`/`ratchet` launchers.

## Integrate into a new project

Prerequisites: the project is a Git repository and `pre-commit` is installed in
the Python environment used by Git hooks.

1. Add this repository as a pinned GitHub dependency of the new project:

```sh
git submodule add https://github.com/b-raisdana/br_pre_commit.git .tools/br_pre_commit
git add .gitmodules .tools/br_pre_commit
```

The consuming repository records the exact `br_pre_commit` commit as a Git
submodule gitlink. It therefore does not depend on the two repositories being
sibling folders and does not silently move when this repository's `main` branch
changes.

2. Create the consuming project's `.pre-commit-config.yaml`. Hook selection remains
   project-owned; use this repository's configuration as a starting point and
   adjust its local test command and file patterns. Shared local entries should
   point inside the submodule; for example:

```sh
cp .tools/br_pre_commit/.pre-commit-config.yaml .pre-commit-config.yaml
```

Then add or adjust project-specific hooks. A shared ratchet entry looks like:

```yaml
- repo: local
  hooks:
    - id: incremental-ratchet
      name: incremental ratchet
      language: system
      entry: .tools/br_pre_commit/ratchet
      pass_filenames: false
      files: ^app/.*\.py$
```

3. Install the clone-local hook from the project root:

```sh
bash .tools/br_pre_commit/install.sh "$PWD"
```

The installer writes the clone-local `.git/hooks/pre-commit` shim. It records the
absolute paths of both the target checkout and this tool checkout, so Git can run
the shared wrapper from any working directory. Run the installed hook directly
to verify the integration:

```sh
.git/hooks/pre-commit
```

On `main`, that verification intentionally fails: direct commits to `main` are
blocked by the shared default. Create a feature branch before normal work:

```sh
git switch -c feature/initial-setup
.git/hooks/pre-commit
```

4. Optionally add a tracked `pre-commit` convenience launcher to the project:

```sh
cp .tools/br_pre_commit/pre-commit ./pre-commit
git add .pre-commit-config.yaml pre-commit
```

After that, `./pre-commit` and an ordinary `git commit` both use the shared
wrapper. Re-run `install.sh` after moving either checkout because the installed
hook records absolute paths.

After cloning a consuming project, initialize the pinned dependency and install
the clone-local hook:

```sh
git submodule update --init --recursive
bash .tools/br_pre_commit/install.sh "$PWD"
```

To upgrade deliberately, update the submodule and commit its new gitlink:

```sh
git -C .tools/br_pre_commit fetch origin
git -C .tools/br_pre_commit checkout <tested-commit-or-tag>
git add .tools/br_pre_commit
```

The target project provides:

- `.pre-commit-config.yaml`: enabled hooks and project-specific hook commands.
- `.br-pre-commit/ratchet/baseline_*.json`: that project's trend baselines.
- optional `.br-pre-commit.toml`: overrides of shared defaults.

See [project-settings.example.toml](project-settings.example.toml) for commented
override examples. Unspecified values inherit from [defaults.toml](defaults.toml).
The defaults protect `main`; set `wrapper.protected-branches = []` only when a
project deliberately permits direct commits, or list additional protected
branch names such as `master`.

For an incremental-ratchet hook backed by the GitHub submodule, use:

```yaml
- repo: local
  hooks:
    - id: incremental-ratchet
      name: incremental ratchet
      language: system
      entry: .tools/br_pre_commit/ratchet
      pass_filenames: false
      files: ^app/.*\.py$
```

## Recovery

On hook failure, snapshots are written inside the target project under
`logs/pre-commit/backup-patches/`. Restore one explicitly with:

```sh
python .tools/br_pre_commit/src/br_pre_commit/recover.py \
  --repo "$PWD" \
  --snapshot logs/pre-commit/backup-patches/<snapshot>
```

Implementation details are in [concurrent-wrapper.md](docs/concurrent-wrapper.md)
and [failure-backup-recovery.md](docs/failure-backup-recovery.md). The ratchet
design is in [incremental-ratchet.md](docs/incremental-ratchet.md).

## Development

```sh
bash install.sh "$PWD"
./pre-commit
python -m pytest -q
python -m py_compile src/br_pre_commit/*.py src/br_pre_commit/incremental_precommit/*.py
```

This repository uses the same shared wrapper it provides to consuming projects.
Its checked-in `.pre-commit-config.yaml` keeps `./pre-commit` usable in a fresh
clone after running the installer. Because this checkout normally remains on
`main`, its own hook is expected to stop at the shared branch guard until work
moves to a feature branch.
