# br_pre_commit package

This package contains the shared runtime used by installed Git hooks:

- `precommit_wrapper` schedules configured hooks, protects branches, logs
  results, and triggers a backup after failure.
- `precommit_wrapper/` schedules configured hooks, protects branches, logs
  results, and triggers a backup after failure.
- `precommit_wrapper/config.py` merges shared defaults with optional project settings.
- `backup/` and `recover` preserve and restore Git working state.
- `sync_skills/` synchronizes project skill mirrors.
- `ratchet/` contains the quality ratchet implementation.

These modules are invoked through the hook installed by `install/install.sh`
or `install/install.ps1`; they are not copied into consuming projects.
