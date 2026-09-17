"""Incremental pre-commit ratchet package.

Modules:
- baseline: content-addressed baseline storage (load/merge/compute/write)
- gate: per-file regression evaluation (touched files vs before state)
- tools: linter/analyzer runners (ruff, mypy, radon, loc)
- details: per-tool detail printers and DETAIL_PRINTERS registry
- main: orchestration entry point
"""

from .baseline import (
    BASELINE_DIR,
    BASELINE_GLOB,
    COMPLEXITY_RANKS,
    EXCLUDE_DIR,
    LOC_MAX_LINES,
    LOC_SLACK,
    MYPY_CODED_ERROR_RE,
    MYPY_UNCODED_ERROR_RE,
    ROOT,
    TARGET,
    XENON_MAX_ABSOLUTE,
    _excluded,
    _line_count,
    _tool_of,
    compute_new_baseline,
    find_baseline_files,
    load_and_consolidate_baselines,
    load_json,
    merge_baselines,
    run,
    run_output,
    write_baseline_file,
)
from .details import (
    DETAIL_PRINTERS,
    print_loc_details,
    print_mypy_details,
    print_ruff_details,
    print_xenon_details,
)
from .gate import (
    TouchedFile,
    _head_line_count,
    _head_worktree,
    _remove_worktree,
    _validate_configured_hooks,
    characterization_test_touched,
    evaluate_file_gate,
    touched_app_python_files,
)
from .tools import (
    RuffViolation,
    XenonBlock,
    XenonData,
    _exclude_tests,
    _group_mypy_by_file,
    _group_mypy_by_rule,
    _group_ruff_by_file,
    _group_ruff_by_rule,
    _group_xenon_by_file,
    _parse_mypy_records,
    _parse_ruff_json,
    _parse_xenon_json,
    _run_current_analyzers,
    _run_current_and_before_analyzers,
    _xenon_total,
    loc_excess_total,
    loc_line_counts,
    mypy_run,
    ruff_run,
    xenon_run,
)


def main() -> int:
    from .__main__ import main as _main

    return _main()


__all__ = [
    # baseline
    "BASELINE_DIR",
    "BASELINE_GLOB",
    "COMPLEXITY_RANKS",
    "EXCLUDE_DIR",
    "LOC_MAX_LINES",
    "LOC_SLACK",
    "MYPY_CODED_ERROR_RE",
    "MYPY_UNCODED_ERROR_RE",
    "ROOT",
    "TARGET",
    "XENON_MAX_ABSOLUTE",
    "_excluded",
    "_line_count",
    "_tool_of",
    "compute_new_baseline",
    "find_baseline_files",
    "load_and_consolidate_baselines",
    "load_json",
    "merge_baselines",
    "run",
    "run_output",
    "write_baseline_file",
    # gate
    "TouchedFile",
    "touched_app_python_files",
    "evaluate_file_gate",
    "_head_worktree",
    "_remove_worktree",
    "_validate_configured_hooks",
    "characterization_test_touched",
    "_head_line_count",
    # main
    "main",
    # details
    "DETAIL_PRINTERS",
    "print_loc_details",
    "print_mypy_details",
    "print_ruff_details",
    "print_xenon_details",
    # tools
    "RuffViolation",
    "XenonBlock",
    "XenonData",
    "_exclude_tests",
    "_run_current_analyzers",
    "_run_current_and_before_analyzers",
    "_group_ruff_by_rule",
    "_group_ruff_by_file",
    "_group_mypy_by_rule",
    "_group_mypy_by_file",
    "_group_xenon_by_file",
    "_xenon_total",
    "_parse_mypy_records",
    "_parse_ruff_json",
    "_parse_xenon_json",
    "loc_line_counts",
    "loc_excess_total",
    "mypy_run",
    "ruff_run",
    "xenon_run",
]
