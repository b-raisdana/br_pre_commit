# br_pre_commit package

This package contains the shared runtime used by installed Git hooks:

- `precommit_wrapper.py` schedules configured hooks, protects branches, logs
  results, and triggers a backup after failure.
- `precommit_config.py` merges shared defaults with optional project settings.
- `backup.py` and `recover.py` preserve and restore Git working state.
- `sync_skill_files.py` synchronizes project skill mirrors.
- `incremental_precommit/` contains the quality ratchet implementation.

These modules are invoked through the repository's shell launchers; they are
not copied into consuming projects.
