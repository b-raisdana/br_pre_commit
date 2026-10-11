"""Read-only entry point for the incremental pre-commit ratchet."""

from __future__ import annotations

import sys

from .common import (
    _analyze_trend,
    _collect_analyzer_results,
    _file_gate_blocked,
    _print_blocked,
    _print_trends,
    _tool_of,
    _tool_totals,
    async_collect_analyzer_results,
    async_get_current_counts,
    compute_new_baseline,
    find_baseline_files,
    get_current_counts,
    load_json,
    merge_baselines,
)
from .config import ratchet_config
from .gate import (
    _head_worktree,
    _remove_worktree,
    _validate_configured_hooks,
    characterization_test_touched,
    touched_app_python_files,
)
from .tools import _run_current_and_before_analyzers, run_current_analyzers


def _load_merged_baseline() -> dict[str, int]:
    files = find_baseline_files()
    merged = merge_baselines([load_json(path) for path in files])
    return {key: value for key, value in merged.items() if value > 0}


def main() -> int:
    unknown = _validate_configured_hooks()
    if unknown:
        print(f"Incremental pre-commit ratchet: warning: unregistered hook(s): {', '.join(unknown)}")

    old_baseline = _load_merged_baseline()
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

    old_baseline = _load_merged_baseline()
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
    _print_trends(regressed, improved, characterization_test_touched)

    tool_totals, tool_baseline_totals = _tool_totals(current_counts, new_baseline, _tool_of)
    print("\nIncremental pre-commit ratchet: OK (no touched file regressed)")
    for tool in sorted(set(tool_totals) | set(tool_baseline_totals)):
        print(f"  {tool}: {tool_totals.get(tool, 0)} / baseline {tool_baseline_totals.get(tool, 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
