# Documentation

This project is consumed as a **pinned git submodule** (`.tools/br_pre_commit`)
under consumer repositories. These pages document its shared infrastructure.
They supplement the root [`README.md`](../README.md) (consumer onboarding and
the submodule workflow) and [`IMPLEMENTATION.md`](../IMPLEMENTATION.md).

- [`concurrent-wrapper.md`](concurrent-wrapper.md) — the shared concurrent
  pre-commit wrapper: hook classification and scheduling, branch protection,
  timeouts, live logging, and advisory lint warnings.
- [`incremental-ratchet.md`](incremental-ratchet.md) — the per-touched-file
  regression gate and the project-wide trend baseline that ratchets debt down.
- [`failure-backup-recovery.md`](failure-backup-recovery.md) — the read-only
  working-state snapshot taken on hook failure and how to restore it with
  `recover.py`.
- [`hook-installer.md`](hook-installer.md) — `install.sh`, the
  `.git/hooks/pre-commit` shim, WSL handling, and the `run`/`ratchet` launchers.
