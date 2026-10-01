# br_pre_commit package

This package contains the shared runtime used by installed Git hooks. They are invoked through the hook installed by `../install.sh` or `../install.ps1`; they are not copied into consuming projects.

## Packages

Each package carries its own README with the details that used to live in module docstrings.

- [`precommit_wrapper/`](precommit_wrapper/README.md) — concurrent hook scheduler, protected-branch guard, log/report writing, backup trigger. See also the root [Recognized hook IDs](../README.md#recognized-hook-ids).
- [`pandera/`](pandera/README.md) — `pandera_validate` runtime DataFrame validation decorator and its content-addressed output dumping.
- [`backup/`](backup/) — full/patch snapshot creation and restore; the `recover` entry point replays a snapshot. Settings in `[tool.br_pre_commit.backup]`.
- [`ratchet/`](ratchet/README.md) — incremental quality ratchet (per-file blocking gate plus non-blocking trend baselines); launcher `python -m src.ratchet` from this repository's root (`python -m br_pre_commit.src.ratchet` from a consuming repository), hook ID `incremental-ratchet`. See also [RATCHET.md](ratchet/RATCHET.md).
- [`sync_skills/`](sync_skills/README.md) — bidirectional `SKILL.md` mirroring across agent directories, run as `python -m src.sync_skills` by the `sync-skill-files` hook.
- [`helper/`](helper/) — shared plumbing: `pyproject.toml` config loading, git subprocess wrapper, repo paths and log dirs, requirement satisfaction, dynamic imports.

## Top-level modules

- `config.py` — `AppConfig` settings loaded from `.env` (`BR_PRE_COMMIT_REPO_ROOT`, `USER_REPO_ROOT`) plus file-name and ratchet hook-ID defaults.
- `check_no_commit_to_main.py` — `no-commit-to-main` hook: blocks direct commits to `protected-branches`.
- `check_no_object_annotations.py` — `no-object-annotations` hook: rejects explicit `object` annotations unless tagged `# ignore: no-object-annotations` on the same line.
- `check_pandera_decorator.py` — `check-pandera-decorator` hook: requires `@pandera_validate`/`@duckdb_cache` on public functions with DataFrame annotations; policy details in [`pandera/README.md`](pandera/README.md#companion-hook).
- `install.py`, [`INSTALL.md`](INSTALL.md) — hook installer that merges the default `.pre-commit-config.yaml` and `pyproject.toml` into a consuming project.
- `git_helper.py` — thin subprocess-backed git helper replacing GitPython; the rationale for not using `Repo.index` is in [`sync_skills/README.md`](sync_skills/README.md#dependency).
