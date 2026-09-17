"""Tool runners and analyzers for the incremental pre-commit ratchet.

Runs linters (ruff, mypy, radon/xenon) and LOC counter, both on current HEAD and
on the before state (via git worktree). Groups results by rule code and by file.
This module is stateless — it only runs tools and returns structured data.
"""

from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypedDict, cast

from .baseline import (  # noqa: F401,E402
    COMPLEXITY_RANKS,
    EXCLUDE_DIR,
    ROOT,
    TARGET,
    XENON_MAX_ABSOLUTE,
    _line_count,
    run,
    run_output,
)


class RuffViolation(TypedDict):
    filename: str
    code: str


class RuffRule(TypedDict):
    code: str


class XenonBlock(TypedDict, total=False):
    rank: str
    lineno: int
    type: str
    name: str


XenonData = dict[str, list[XenonBlock]]


def _parse_ruff_json(stdout: str) -> list[RuffViolation]:
    try:
        return cast(list[RuffViolation], json.loads(stdout or "[]"))
    except json.JSONDecodeError:
        return []


def ruff_run(root: Path | None = None) -> list[RuffViolation]:
    root = ROOT if root is None else root
    stdout = run("ruff", "check", TARGET, "--output-format=json", cwd=root)
    return _parse_ruff_json(stdout)


def _group_ruff_by_rule(violations: list[RuffViolation]) -> dict[str, int]:
    return dict(Counter(f"ruff:{violation['code']}" for violation in violations if violation.get("code")))


def _group_ruff_by_file(violations: list[RuffViolation], root: Path | None = None) -> dict[str, int]:
    root = ROOT if root is None else root
    return dict(
        Counter(
            Path(violation["filename"]).relative_to(root).as_posix()
            for violation in violations
            if violation.get("filename")
        )
    )


def _parse_mypy_records(output: str) -> list[tuple[str, str]]:
    from .baseline import MYPY_CODED_ERROR_RE, MYPY_UNCODED_ERROR_RE  # noqa: F402,E402

    records: list[tuple[str, str]] = []
    for line in output.splitlines():
        coded = MYPY_CODED_ERROR_RE.search(line)
        if coded:
            records.append((line.split(":", 1)[0], coded.group(1)))
        elif MYPY_UNCODED_ERROR_RE.search(line):
            records.append((line.split(":", 1)[0], "uncoded"))
    return records


def mypy_run(root: Path | None = None) -> list[tuple[str, str]]:
    root = ROOT if root is None else root
    output = run_output("mypy", "--config-file", str(root / "pyproject.toml"), ".", cwd=root / TARGET)
    return _parse_mypy_records(output)


def _group_mypy_by_rule(records: list[tuple[str, str]]) -> dict[str, int]:
    return dict(Counter(f"mypy:{code}" for _file, code in records))


def _group_mypy_by_file(records: list[tuple[str, str]]) -> dict[str, int]:
    return dict(Counter(f"{TARGET}/{file}" for file, _code in records))


def _parse_xenon_json(stdout: str) -> XenonData:
    try:
        return cast(XenonData, json.loads(stdout or "{}"))
    except json.JSONDecodeError:
        return {}


def xenon_run(root: Path | None = None) -> XenonData:
    root = ROOT if root is None else root
    stdout = run("radon", "cc", TARGET, "-j", "-i", f"tests,{EXCLUDE_DIR}", "--show-closures", cwd=root)
    return _parse_xenon_json(stdout)


def _xenon_total(data: XenonData, max_absolute: str | None = None) -> int:
    max_absolute = XENON_MAX_ABSOLUTE if max_absolute is None else max_absolute
    threshold = COMPLEXITY_RANKS.index(max_absolute)
    return sum(
        1
        for blocks in data.values()
        for block in blocks
        if COMPLEXITY_RANKS.index(block.get("rank") or "A") > threshold
    )


def _group_xenon_by_file(data: XenonData, max_absolute: str | None = None) -> dict[str, int]:
    max_absolute = XENON_MAX_ABSOLUTE if max_absolute is None else max_absolute
    threshold = COMPLEXITY_RANKS.index(max_absolute)
    result: dict[str, int] = {}
    for file_path, blocks in data.items():
        count = sum(1 for block in blocks if COMPLEXITY_RANKS.index(block.get("rank") or "A") > threshold)
        if count:
            result[file_path] = count
    return result


def loc_line_counts(root: Path | None = None) -> dict[str, int]:
    root = ROOT if root is None else root
    counts: dict[str, int] = {}
    for path in (root / TARGET).rglob("*.py"):
        if "__pycache__" in path.parts or EXCLUDE_DIR in path.parts:
            continue
        counts[path.relative_to(root).as_posix()] = _line_count(path)
    return counts


def _exclude_tests(paths: list[Path]) -> list[Path]:
    """Drop any path that lives under a tests directory."""
    return [path for path in paths if "tests" not in path.parts]


def loc_excess_total(line_counts: dict[str, int], max_lines: int = 300) -> int:
    return sum(max(0, n - max_lines) for n in line_counts.values())


def _run_current_analyzers() -> tuple[list[RuffViolation], list[tuple[str, str]], XenonData, dict[str, int]]:
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="ratchet") as executor:
        ruff_future = executor.submit(ruff_run)
        mypy_future = executor.submit(mypy_run)
        xenon_future = executor.submit(xenon_run)
        loc_future = executor.submit(loc_line_counts)
        return ruff_future.result(), mypy_future.result(), xenon_future.result(), loc_future.result()


def _run_current_and_before_analyzers(
    before_root: Path,
) -> tuple[
    list[RuffViolation],
    list[tuple[str, str]],
    XenonData,
    dict[str, int],
    dict[str, dict[str, int]],
]:
    with ThreadPoolExecutor(max_workers=7, thread_name_prefix="ratchet-all") as executor:
        current_ruff = executor.submit(ruff_run)
        current_mypy = executor.submit(mypy_run)
        current_xenon = executor.submit(xenon_run)
        current_loc = executor.submit(loc_line_counts)
        before_ruff = executor.submit(ruff_run, before_root)
        before_mypy = executor.submit(mypy_run, before_root)
        before_xenon = executor.submit(xenon_run, before_root)

        ruff_violations = current_ruff.result()
        mypy_records = current_mypy.result()
        xenon_data = current_xenon.result()
        loc_counts = current_loc.result()
        before_by_file = {
            "mypy": _group_mypy_by_file(before_mypy.result()),
            "ruff": _group_ruff_by_file(before_ruff.result(), root=before_root),
            "xenon": _group_xenon_by_file(before_xenon.result()),
        }
    return ruff_violations, mypy_records, xenon_data, loc_counts, before_by_file
