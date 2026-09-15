"""Main entry point for the incremental pre-commit ratchet."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ratchet_check import TouchedFile


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
    current_analyzers: Callable[[], tuple[list[dict], list[tuple[str, str]], dict, dict[str, int]]],
    current_and_before_analyzers: Callable[
        [Path], tuple[list[dict], list[tuple[str, str]], dict, dict[str, int], dict[str, dict[str, int]]]
    ],
) -> tuple[list[dict], list[tuple[str, str]], dict, dict[str, int], dict[str, dict[str, int]]]:
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
    ruff_violations: list[dict],
    mypy_records: list[tuple[str, str]],
    xenon_data: dict,
    loc_counts: dict[str, int],
) -> dict[str, int]:
    from ratchet_check import _group_mypy_by_rule, _group_ruff_by_rule, _xenon_total  # noqa: F402,E402
    from ratchet_check_tools import loc_excess_total  # noqa: F402,E402

    return {
        **_group_ruff_by_rule(ruff_violations),
        **_group_mypy_by_rule(mypy_records),
        "xenon": _xenon_total(xenon_data),
        "loc": loc_excess_total(loc_counts),
    }


def _file_gate_blocked(
    touched: list[TouchedFile],
    ruff_violations: list[dict],
    mypy_records: list[tuple[str, str]],
    xenon_data: dict,
    before_by_file: dict[str, dict[str, int]],
) -> list[tuple[str, Path, int, int]]:
    if not touched:
        return []
    from ratchet_check import (  # noqa: F402,E402
        _group_mypy_by_file,
        _group_ruff_by_file,
        _group_xenon_by_file,
        evaluate_file_gate,
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
    from ratchet_check import write_baseline_file  # noqa: F402,E402

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
    from ratchet_check import (  # noqa: F402,E402
        LOC_MAX_LINES,
        LOC_SLACK,
        _head_worktree,
        _remove_worktree,
        _tool_of,
        _validate_configured_hooks,
        characterization_test_touched,
        compute_new_baseline,
        load_and_consolidate_baselines,
        touched_app_python_files,
    )
    from ratchet_check_tools import _run_current_analyzers, _run_current_and_before_analyzers  # noqa: F402,E402

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
    from ratchet_check import run_output  # noqa: F402,E402

    if not paths:
        print("    no files to inspect")
        return
    output = run_output("ruff", "check", *(path.as_posix() for path in paths))
    print(output.rstrip() or "    ruff reported no errors on these files")


def print_mypy_details(paths: list[Path]) -> None:
    from ratchet_check import ROOT, TARGET, run_output  # noqa: F402,E402

    app_paths = [path.relative_to(TARGET).as_posix() for path in paths]
    if not app_paths:
        print("    no files to inspect")
        return
    output = run_output("mypy", "--config-file", str(ROOT / "pyproject.toml"), *app_paths, cwd=ROOT / TARGET)
    print(output.rstrip() or "    mypy reported no errors on these files")


def print_xenon_details(paths: list[Path], max_absolute: str = "B") -> None:
    from ratchet_check import (  # noqa: F402,E402
        COMPLEXITY_RANKS,
        ROOT,
        TARGET,
        XENON_MAX_ABSOLUTE,
        _exclude_tests,
        _parse_xenon_json,
        run,
    )

    paths = _exclude_tests(paths)
    if not paths:
        print("    no files to inspect")
        return
    stdout = run("radon", "cc", TARGET, "-j", "-i", "tests,archive_not_used_trash", "--show-closures", cwd=ROOT)
    data = _parse_xenon_json(stdout)
    threshold = COMPLEXITY_RANKS.index(XENON_MAX_ABSOLUTE)
    printed = False
    for file_path, blocks in sorted(data.items()):
        for block in blocks:
            rank = block.get("rank", "A")
            if COMPLEXITY_RANKS.index(rank) <= threshold:
                continue
            print(f"    {file_path}:{block.get('lineno')} {block.get('type')} {block.get('name')} rank {rank}")
            printed = True
    if not printed:
        print(f"    xenon/radon reported no rank > {XENON_MAX_ABSOLUTE} blocks on these files")


def print_loc_details(paths: list[Path], max_lines: int = 300) -> None:
    from ratchet_check import LOC_SLACK, ROOT, _line_count  # noqa: F402,E402

    for path in paths:
        print(f"    {path.as_posix()}: {_line_count(ROOT / path)} lines (cap {max_lines}, slack {LOC_SLACK})")


DETAIL_PRINTERS: dict[str, Callable[[list[Path]], None]] = {
    "ruff": print_ruff_details,
    "mypy": print_mypy_details,
    "xenon": print_xenon_details,
    "loc": print_loc_details,
}


if __name__ == "__main__":
    sys.exit(main())
