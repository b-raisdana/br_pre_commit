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
    baseline_current_state, find_baseline_files,
)

log = __import__("logging").getLogger(__name__)


def main():  # override: RatchetConfigOverride | None = None):
    """Synchronous main entry point for baseline operations with optional config override."""
    for old_baseline in find_baseline_files():
        old_baseline.unlink()
    asyncio.run(baseline_current_state())
    # # if override is not None:
    # #     with RatchetSettingsOverride(override):
    # old_baseline = load_and_consolidate_baselines()
    # from .tools import _run_current_analyzers
    # from .common import get_current_counts
    #
    # ruff_violations, mypy_records, xenon_data, loc_counts = _run_current_analyzers()
    # current_counts = get_current_counts(ruff_violations, mypy_records, xenon_data, loc_counts)
    # current_counts = {k: v for k, v in current_counts.items() if v > 0}
    # new_baseline = compute_new_baseline(old_baseline, current_counts)
    # write_new_baseline(old_baseline, new_baseline)
    # # else:
    # #     old_baseline = load_and_consolidate_baselines()
    # #     from .tools import _run_current_analyzers
    # #     from .common import get_current_counts
    # #
    # #     ruff_violations, mypy_records, xenon_data, loc_counts = _run_current_analyzers()
    # #     current_counts = get_current_counts(ruff_violations, mypy_records, xenon_data, loc_counts)
    # #     current_counts = {k: v for k, v in current_counts.items() if v > 0}
    # #     new_baseline = compute_new_baseline(old_baseline, current_counts)
    # #     write_new_baseline(old_baseline, new_baseline)


if __name__ == "__main__":
    sys.exit(main())
