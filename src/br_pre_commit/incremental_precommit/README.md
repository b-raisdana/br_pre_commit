# Incremental pre-commit ratchet

`ratchet_check.py` implements the shared per-file regression gate and maintains
project-owned baselines under `<project>/.br-pre-commit/ratchet/`.

Use the root [`ratchet`](../../../ratchet) launcher from a consuming project's
`.pre-commit-config.yaml`. Design details and baseline behavior are documented
in [`RATCHET.md`](../../../RATCHET.md).
