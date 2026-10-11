# 0.4.9 → 0.5.0

## Features

- **hooks**: Add `no-commit-to-trunk` hook and enhance backup, ratchet, and sync-skills modules (`5ed4edc`)
  - Rename `check_no_commit_to_main` to `check_no_commit_to_trunk` hook.
  - Add `no-object-annotations` hook to block `object` type annotations.
  - Add backup module README and update `Manifest` model.
  - Replace ratchet `RATCHET.md` with `DEVELOPMENT.md` (developer documentation).
  - Add `sync_skills` configuration module with `SyncSkillsConfig`.
  - Update `precommit_wrapper` config with `pydantic-settings` and `populate_by_name`.
  - Update ratchet baseline files (content-addressed renames).
  - Update project documentation (README, FEATURE_ANALYSIS, pyproject.toml).

## Refactors

- **core**: Implement configuration management and content-addressed output dumping (`62e22de`)
  - Add `BrPanderaConfig` via `src/br_pandera/config.py` for environment settings.
  - Implement `content_hash` utility using CRC-32 for deterministic filename generation.
  - Add `output_dump.py` for content-addressed dumping of `pandera_validate` return values (Parquet and JSON).
  - Move `content_hash.py` and `output_dump.py` into the `br_pandera` core package.

- **core**: Update supported agents list (`f06dffe`)
  - Remove "codex" and "qoder" from the AGENTS list; replace with a generic "agents" entry.

- **output_dump**: Simplify frame writing logic (`a1720b0`)
  - Remove redundant `_parquet_payload` helper; integrate parquet serialization directly into `_write_frame`.
  - Update `_write_frame` to handle both `pd.DataFrame` and `Array` types via `_extractable_frame`.

- **install**: Correct directory resolution and Python path detection (`e965311`)
  - Distinguish repository directory from user's repository directory in `install.ps1` and `install.sh`.
  - Pass user repository directory as explicit argument to `src.install`.
  - Improve Python interpreter detection with validation before proceeding.

## Fixes

- **type-checking**: Suppress mypy `explicit-any` and `object-annotation` warnings; update ratchet baselines (`f4c0ce5`)
  - Add `# type: ignore[explicit-any]` (later `# type: ignore[misc]`) to `FromPyProjectTomlConfig` subclasses.
  - Add `# ignore: no-object-annotations` markers where explicit `object` annotations are needed.
  - Add `typing.cast()` for type safety in `helper/git.py`, `backup/__main__.py`, `precommit_wrapper/report.py`, and `ratchet/gate.py`.
  - Refactor `src/install.py` with typed helpers (`PreCommitConfig`, `PreCommitRepo`, `PreCommitHook`).
  - Refactor `src/check_pandera_decorator.py` with `_get_attribute_parts()` helper.
  - Fix `src/ratchet/details.py` imports to use `common` module instead of non-existent `baseline.run_output`.
  - Update ratchet baselines: delete `baseline_04ffc269`, `baseline_26cfb65d`, `baseline_40a3cb88`; add `baseline_c19cc53f`, `baseline_e1344de5`, `baseline_e9527ee6`.
  - Exclude `logs/pre-commit/backup-patches/` from mypy in `pyproject.toml`.

## Chores

- **docs**: Update documentation and gitignore (`616a96e`)
  - Add `no-object-annotations` to README hook list.
  - Remove obsolete ratchet README link from README table.
  - Add `node_modules` to `.gitignore`.
