# br_pre_commit

Shared pre-commit infrastructure for python repositories. It owns the concurrent
wrapper, incremental ratchet, failure backup/recovery, hook installer, and their
tests. Projects keep only their own hook selection, optional overrides, and
project-specific ratchet baselines.

## Integrate into a new project

Prerequisites: the project is a Git repository, `pre-commit` is installed in
the Python environment used by Git hooks, and this repository is available as a
sibling directory:

```text
code/
├── br_pre_commit/
└── my_project/
```

1. Create `my_project/.pre-commit-config.yaml`. Hook selection remains
   project-owned; use this repository's configuration as a starting point and
   adjust its local test command and file patterns.

2. From `my_project`, install the clone-local hook:

```sh
bash ../br_pre_commit/install.sh "$PWD"
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

3. Optionally add a tracked `pre-commit` convenience launcher to the project:

```sh
cp ../br_pre_commit/pre-commit ./pre-commit
git add .pre-commit-config.yaml pre-commit
```

After that, `./pre-commit` and an ordinary `git commit` both use the shared
wrapper. Re-run `install.sh` after moving either checkout because the installed
hook records absolute paths.

The target project provides:

- `.pre-commit-config.yaml`: enabled hooks and project-specific hook commands.
- `.br-pre-commit/ratchet/baseline_*.json`: that project's trend baselines.
- optional `.br-pre-commit.toml`: overrides of shared defaults.

See [project-settings.example.toml](project-settings.example.toml) for commented
override examples. Unspecified values inherit from [defaults.toml](defaults.toml).
The defaults protect `main`; set `wrapper.protected-branches = []` only when a
project deliberately permits direct commits, or list additional protected
branch names such as `master`.

For a local incremental-ratchet hook, use:

```yaml
- repo: local
  hooks:
    - id: incremental-ratchet
      name: incremental ratchet
      language: system
      entry: ../br_pre_commit/ratchet
      pass_filenames: false
      files: ^app/.*\.py$
```

## Recovery

On hook failure, snapshots are written inside the target project under
`logs/pre-commit/backup-patches/`. Restore one explicitly with:

```sh
python ../br_pre_commit/src/br_pre_commit/recover.py \
  --repo "$PWD" \
  --snapshot logs/pre-commit/backup-patches/<snapshot>
```

Implementation details are in [IMPLEMENTATION.md](IMPLEMENTATION.md), and the
ratchet design is in [RATCHET.md](RATCHET.md).

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
