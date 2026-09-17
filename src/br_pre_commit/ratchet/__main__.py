"""Main entry point for the incremental pre-commit ratchet.

Orchestrates the full ratchet run: loads baselines, runs analyzers (current + before),
evaluates per-file gate, computes new baseline, prints trends. This is the only
module with side effects (stdout, git staging, file writes).
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from .gate import TouchedFile
from .tools import RuffViolation, XenonData

AnalyzerResult = tuple[list[RuffViolation], list[tuple[str, str]], XenonData, dict[str, int]]
AnalyzerResultWithBefore = tuple[
    list[RuffViolation],
    list[tuple[str, str]],
    XenonData,
    dict[str, int],
    dict[str, dict[str, int]],
]


def get_enabled_ruff_codes() -> set[str]:
    """Get all ruff rule codes enabled by the current config."""
    try:
        result = subprocess.run(
            ["ruff", "rule", "--all", "--output-format=json"],
            capture_output=True,
            text=True,
            check=True,
        )
        rules = json.loads(result.stdout)
        selected = ["E", "F", "I", "UP", "B", "C4", "SIM", "W"]
        return {r["code"] for r in rules if any(r["code"].startswith(s) for s in selected)}
    except Exception:
        return set()


def _analyze_trend(
    old_baseline: dict[str, int], current_counts: dict[str, int]
) -> tuple[list[tuple[str, int, int]], list[tuple[str, int, int]]]:
    regressed: list[tuple[str, int, int]] = []
    improved: list[tuple[str, int, int]] = []
    for key in sorted(set(old_baseline) | set(current_counts)):
        current = current_counts.get(key, 0)
        base = old_baseline.get(key)
        if base is None:
            print(f"[{key}] no baseline yet - bootstrapping at {current}")
        elif current > base:
            regressed.append((key, base, current))
        elif current < base:
            improved.append((key, base, current))
    return regressed, improved


def _collect_analyzer_results(
    touched: list[TouchedFile],
    head_worktree: Callable[[], Path | None],
    remove_worktree: Callable[[Path], None],
    current_analyzers: Callable[[], AnalyzerResult],
    current_and_before_analyzers: Callable[[Path], AnalyzerResultWithBefore],
) -> AnalyzerResultWithBefore:
    before_by_file: dict[str, dict[str, int]] = {"mypy": {}, "ruff": {}, "xenon": {}}
    worktree = head_worktree() if touched else None
    try:
        if worktree is None:
            ruff_violations, mypy_records, xenon_data, loc_counts = current_analyzers()
            return ruff_violations, mypy_records, xenon_data, loc_counts, before_by_file
        return current_and_before_analyzers(worktree)
    finally:
        if worktree is not None:
            remove_worktree(worktree)


def _current_counts(
    ruff_violations: list[RuffViolation],
    mypy_records: list[tuple[str, str]],
    xenon_data: XenonData,
    loc_counts: dict[str, int],
) -> dict[str, int]:
    from .tools import (  # noqa: F402,E402
        _group_mypy_by_rule,
        _group_ruff_by_rule,
        _xenon_total,
        loc_excess_total,
    )

    return {
        **_group_ruff_by_rule(ruff_violations),
        **_group_mypy_by_rule(mypy_records),
        "xenon": _xenon_total(xenon_data),
        "loc": loc_excess_total(loc_counts),
    }


def _file_gate_blocked(
    touched: list[TouchedFile],
    ruff_violations: list[RuffViolation],
    mypy_records: list[tuple[str, str]],
    xenon_data: XenonData,
    before_by_file: dict[str, dict[str, int]],
) -> list[tuple[str, Path, int, int]]:
    if not touched:
        return []
    from .gate import evaluate_file_gate  # noqa: F402,E402
    from .tools import (  # noqa: F402,E402
        _group_mypy_by_file,
        _group_ruff_by_file,
        _group_xenon_by_file,
    )

    after_by_file = {
        "mypy": _group_mypy_by_file(mypy_records),
        "ruff": _group_ruff_by_file(ruff_violations),
        "xenon": _group_xenon_by_file(xenon_data),
    }
    return evaluate_file_gate(touched, after_by_file, before_by_file)


def _print_blocked(blocked: list[tuple[str, Path, int, int]], max_lines: int, slack: int) -> None:
    print("Incremental pre-commit ratchet: BLOCKED - a touched file got worse\n")
    blocked_paths: set[Path] = set()
    for tool, path, before, after in blocked:
        print(f"  {tool} in {path.as_posix()}: {before} -> {after}")
        blocked_paths.add(path)
    print("\nDetails:")
    printed_tools: set[str] = set()
    for tool, _path, _before, _after in blocked:
        base_tool = "loc" if tool.startswith("loc") else tool
        if base_tool in printed_tools:
            continue
        printed_tools.add(base_tool)
        print(f"\n  {base_tool}:")
        DETAIL_PRINTERS[base_tool](sorted(blocked_paths))
    print(
        f"\nEach touched file is checked against its own pre-commit state (new files against a zero "
        f"baseline, and a {max_lines}-line cap for loc). mypy/ruff/xenon allow zero increase; loc "
        f"allows a {slack}-line slack. An oversized file can be split into two+ files to fit under "
        "the loc cap - that's a legitimate way through this gate, but a meaningful split, not "
        "arbitrary chopping to dodge the check."
    )


def _write_new_baseline(old_baseline: dict[str, int], new_baseline: dict[str, int]) -> None:
    if new_baseline == old_baseline:
        return
    from .baseline import write_baseline_file  # noqa: F402,E402

    write_baseline_file(new_baseline)


def _print_trends(
    regressed: list[tuple[str, int, int]],
    improved: list[tuple[str, int, int]],
    characterization_test_touched: Callable[[], bool],
) -> None:
    if regressed:
        print("Incremental pre-commit ratchet: project-wide count rose (trend only, does not block)\n")
        for key, base, current in regressed:
            print(f"  {key}: baseline {base} -> now {current} (+{current - base}); no touched file regressed")
    if not improved:
        return
    print("Incremental pre-commit ratchet: progress locked in\n")
    for key, base, current in improved:
        print(f"  {key}: baseline {base} -> {current} (-{base - current} fixed)")
    if characterization_test_touched():
        return
    print(
        "\nNote: this commit fixed pre-existing problems, but doesn't touch "
        "app/tests/{characterization,unit,regression}. If any of these were "
        "behavior-affecting fixes (not just type annotations/formatting), pin the before/after "
        "behavior with a characterization test first - see the test-strategy skill. This is a "
        "reminder, not a block: this repo's mutation-safety net is test discipline, not a mutation-testing "
        "tool (see docs/infrastructure.md#pre-commit)."
    )


def _tool_totals(
    current_counts: dict[str, int], new_baseline: dict[str, int], tool_of: Callable[[str], str]
) -> tuple[dict[str, int], dict[str, int]]:
    tool_totals: dict[str, int] = {"ruff": 0, "mypy": 0, "xenon": 0, "loc": 0}
    tool_baseline_totals: dict[str, int] = {"ruff": 0, "mypy": 0, "xenon": 0, "loc": 0}
    for key, count in current_counts.items():
        tool_totals[tool_of(key)] = tool_totals.get(tool_of(key), 0) + count
    for key, count in new_baseline.items():
        tool_baseline_totals[tool_of(key)] = tool_baseline_totals.get(tool_of(key), 0) + count
    return tool_totals, tool_baseline_totals


def main() -> int:
    from .baseline import (  # noqa: F402,E402
        LOC_MAX_LINES,
        LOC_SLACK,
        _tool_of,
        compute_new_baseline,
        load_and_consolidate_baselines,
    )
    from .gate import (  # noqa: F402,E402
        _head_worktree,
        _remove_worktree,
        _validate_configured_hooks,
        characterization_test_touched,
        touched_app_python_files,
    )
    from .tools import _run_current_analyzers, _run_current_and_before_analyzers  # noqa: F402,E402

    unknown = _validate_configured_hooks()
    if unknown:
        print(f"Incremental pre-commit ratchet: warning: unregistered hook(s): {', '.join(unknown)}")
    old_baseline = load_and_consolidate_baselines()
    touched = touched_app_python_files()
    results = _collect_analyzer_results(
        touched,
        _head_worktree,
        _remove_worktree,
        _run_current_analyzers,
        _run_current_and_before_analyzers,
    )
    ruff_violations, mypy_records, xenon_data, loc_counts, before_by_file = results
    current_counts = _current_counts(ruff_violations, mypy_records, xenon_data, loc_counts)

    # Ensure all enabled ruff rule codes have a baseline entry (zero if no violations)
    enabled_ruff_codes = get_enabled_ruff_codes()
    for code in enabled_ruff_codes:
        key = f"ruff:{code}"
        if key not in old_baseline:
            old_baseline[key] = 0

    regressed, improved = _analyze_trend(old_baseline, current_counts)
    blocked = _file_gate_blocked(touched, ruff_violations, mypy_records, xenon_data, before_by_file)
    if blocked:
        _print_blocked(blocked, LOC_MAX_LINES, LOC_SLACK)
        return 1

    new_baseline = compute_new_baseline(old_baseline, current_counts)
    _write_new_baseline(old_baseline, new_baseline)
    _print_trends(regressed, improved, characterization_test_touched)
    tool_totals, tool_baseline_totals = _tool_totals(current_counts, new_baseline, _tool_of)
    print("\nIncremental pre-commit ratchet: OK (no touched file regressed)")
    for tool in sorted(set(tool_totals) | set(tool_baseline_totals)):
        print(f"  {tool}: {tool_totals.get(tool, 0)} / baseline {tool_baseline_totals.get(tool, 0)}")
    return 0


def print_ruff_details(paths: list[Path]) -> None:
    from .details import print_ruff_details as _print  # noqa: F402,E402

    _print(paths)


def print_mypy_details(paths: list[Path]) -> None:
    from .details import print_mypy_details as _print  # noqa: F402,E402

    _print(paths)


def print_xenon_details(paths: list[Path], max_absolute: str = "B") -> None:
    from .details import print_xenon_details as _print  # noqa: F402,E402

    _print(paths, max_absolute=max_absolute)


def print_loc_details(paths: list[Path], max_lines: int = 300) -> None:
    from .details import print_loc_details as _print  # noqa: F402,E402

    _print(paths, max_lines=max_lines)


DETAIL_PRINTERS: dict[str, Callable[[list[Path]], None]] = {
    "ruff": print_ruff_details,
    "mypy": print_mypy_details,
    "xenon": print_xenon_details,
    "loc": print_loc_details,
}


if __name__ == "__main__":
    sys.exit(main())
