# br_pre_commit

Shared pre-commit infrastructure for Brais's repositories. It owns the concurrent
wrapper, incremental ratchet, failure backup/recovery, hook installer, and their
tests. Projects keep only their own hook selection, optional overrides, and
project-specific ratchet baselines.

## Use from a sibling project

```sh
bash ../br_pre_commit/install.sh "$PWD"
./pre-commit
```

The installer writes the clone-local `.git/hooks/pre-commit` shim. It records the
absolute paths of both the target checkout and this tool checkout, so Git can run
the shared wrapper from any working directory.

The target project provides:

- `.pre-commit-config.yaml`: enabled hooks and project-specific hook commands.
- `.br-pre-commit/ratchet/baseline_*.json`: that project's trend baselines.
- optional `.br-pre-commit.toml`: overrides of shared defaults.

See [project-settings.example.toml](project-settings.example.toml) for commented
override examples. Unspecified values inherit from [defaults.toml](defaults.toml).

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
clone after running the installer.
