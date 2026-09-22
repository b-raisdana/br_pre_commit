"""Main entry point for the incremental pre-commit ratchet.

Orchestrates the full ratchet run: loads baselines, runs analyzers (current + before),
evaluates per-file gate, computes new baseline, prints trends. This is the only
module with side effects (stdout, git staging, file writes).
"""

from __future__ import annotations

import sys

from .common import (
    _analyze_trend,
    _collect_analyzer_results,
    _file_gate_blocked,
    _print_blocked,
    _print_trends,
    _tool_totals,
    _write_new_baseline,
    async_collect_analyzer_results,
    async_get_current_counts,
    async_load_and_consolidate_baselines,
    async_write_new_baseline,
    compute_new_baseline,
    get_current_counts,
    load_and_consolidate_baselines, _tool_of,
)
from .config import ratchet_config
from .gate import (
    _head_worktree,
    _remove_worktree,
    _validate_configured_hooks,
    characterization_test_touched,
    touched_app_python_files,
)
from .tools import run_current_analyzers, _run_current_and_before_analyzers


def main() -> int:
    unknown = _validate_configured_hooks()
    if unknown:
        print(f"Incremental pre-commit ratchet: warning: unregistered hook(s): {', '.join(unknown)}")

    old_baseline = load_and_consolidate_baselines()
    touched = touched_app_python_files()
    results = _collect_analyzer_results(
        touched,
        _head_worktree,
        _remove_worktree,
        run_current_analyzers,
        _run_current_and_before_analyzers,
    )
    ruff_violations, mypy_records, xenon_data, loc_counts, before_by_file = results
    current_counts = get_current_counts(ruff_violations, mypy_records, xenon_data, loc_counts)
    current_counts = {k: v for k, v in current_counts.items() if v > 0}

    regressed, improved = _analyze_trend(old_baseline, current_counts)
    blocked = _file_gate_blocked(touched, ruff_violations, mypy_records, xenon_data, before_by_file)
    if blocked:
        _print_blocked(blocked, ratchet_config.loc_max_lines, ratchet_config.loc_line_growth_slack)
        return 1

    new_baseline = compute_new_baseline(old_baseline, current_counts)
    _write_new_baseline(old_baseline, new_baseline)
    _print_trends(regressed, improved, characterization_test_touched)

    tool_totals, tool_baseline_totals = _tool_totals(current_counts, new_baseline, _tool_of)
    print("\nIncremental pre-commit ratchet: OK (no touched file regressed)")
    for tool in sorted(set(tool_totals) | set(tool_baseline_totals)):
        print(f"  {tool}: {tool_totals.get(tool, 0)} / baseline {tool_baseline_totals.get(tool, 0)}")
    return 0


async def async_main() -> int:
    """Async version of main for future use."""
    unknown = _validate_configured_hooks()
    if unknown:
        print(f"Incremental pre-commit ratchet: warning: unregistered hook(s): {', '.join(unknown)}")

    old_baseline = await async_load_and_consolidate_baselines()
    touched = touched_app_python_files()
    results = await async_collect_analyzer_results(
        touched,
        _head_worktree,
        _remove_worktree,
        run_current_analyzers,
        _run_current_and_before_analyzers,
    )
    ruff_violations, mypy_records, xenon_data, loc_counts, before_by_file = results
    current_counts = await async_get_current_counts(ruff_violations, mypy_records, xenon_data, loc_counts)
    current_counts = {k: v for k, v in current_counts.items() if v > 0}

    regressed, improved = _analyze_trend(old_baseline, current_counts)
    blocked = _file_gate_blocked(touched, ruff_violations, mypy_records, xenon_data, before_by_file)
    if blocked:
        _print_blocked(blocked, ratchet_config.loc_max_lines, ratchet_config.loc_line_growth_slack)
        return 1

    new_baseline = compute_new_baseline(old_baseline, current_counts)
    await async_write_new_baseline(old_baseline, new_baseline)
    _print_trends(regressed, improved, characterization_test_touched)

    tool_totals, tool_baseline_totals = _tool_totals(current_counts, new_baseline, _tool_of)
    print("\nIncremental pre-commit ratchet: OK (no touched file regressed)")
    for tool in sorted(set(tool_totals) | set(tool_baseline_totals)):
        print(f"  {tool}: {tool_totals.get(tool, 0)} / baseline {tool_baseline_totals.get(tool, 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())