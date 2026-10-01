"""Baseline management for the incremental pre-commit ratchet.

Handles content-addressed baseline storage: JSON files named by SHA-256 hash of their
sorted, indented content. Multiple baselines are merged (union of keys, minimum value kept)
and consolidated into a single file on each run. This module knows nothing about linters
or touched files — only dict[str, int] baselines and their persistence.
"""

from __future__ import annotations

import asyncio
import sys

from .common import (
    baseline_current_state,
    find_baseline_files,
)

log = __import__("logging").getLogger(__name__)


def main():  # override: RatchetConfigOverride | None = None):
    """Synchronous main entry point for baseline operations with optional config override."""
    for old_baseline in find_baseline_files():
        old_baseline.unlink()
    asyncio.run(baseline_current_state())


if __name__ == "__main__":
    sys.exit(main())
