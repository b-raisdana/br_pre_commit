# Changelog: 0.0.0 to 0.1.0

## Features

- **pre-commit**: Update hooks and refactor backup module (`dfc9eda`)
  - Added `incremental-ratchet`, `pytest-fast`, `pytest-integration-collect`, `integration-tests`, `check-pandera-decorator`, and `no-commit-to-main` hooks to `.pre-commit-config.yaml`.
  - Refactored `src/backup` to use proper package-relative imports.
  - Moved `Manifest` to a dedicated `models.py` file.
  - Updated `README.md` with new installation instructions and hook documentation.
  - Updated `.vscode/settings.json` to include `pandera` in recognized languages.

## Refactors

- **config**: Migrate to Pydantic-based configuration management (`42ca140`)
  - Introduced `AppConfig` and `FromPyProjectTomlConfig` for structured loading of settings from `pyproject.toml`.
  - Refactored `ratchet`, `backup`, and `precommit_wrapper` to use dedicated Pydantic models (`RatchetConfig`, `BackupConfig`, `WrapperConfig`).
  - Decoupled modules from environment variables and hardcoded paths by centralizing path resolution in `src/helper/paths.py`.
  - Replaced `GitPython` dependency with a thin `subprocess` wrapper in `src/helper/git.py`.
  - Updated all internal modules (`backup`, `ratchet`, `sync_skills`, `precommit_wrapper`) to consume configuration via these new models.
  - Added `requirements.txt` to explicitly define runtime dependencies.
  - Improved test suite to validate the new configuration loading logic and environment checks.

## Chores

- Ignore `.env files` (`7b2b9c5`)
