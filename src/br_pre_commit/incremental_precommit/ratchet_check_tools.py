"""Tool runners and analyzers for the incremental pre-commit ratchet."""

from __future__ import annotations

__all__ = [
    "_parse_ruff_json",
    "ruff_run",
    "_group_ruff_by_rule",
    "_group_ruff_by_file",
    "_parse_mypy_records",
    "mypy_run",
    "_group_mypy_by_rule",
    "_group_mypy_by_file",
    "_parse_xenon_json",
    "xenon_run",
    "_xenon_total",
    "_group_xenon_by_file",
    "loc_line_counts",
    "loc_excess_total",
    "_run_current_analyzers",
    "_run_current_and_before_analyzers",
]

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _parse_ruff_json(stdout: str) -> list[dict]:
    try:
        return json.loads(stdout or "[]")
    except json.JSONDecodeError:
        return []


def ruff_run(root: Path | None = None) -> list[dict]:
    from ratchet_check import ROOT, TARGET, run

    root = ROOT if root is None else root
    stdout = run("ruff", "check", TARGET, "--output-format=json", cwd=root)
    return _parse_ruff_json(stdout)


def _group_ruff_by_rule(violations: list[dict]) -> dict[str, int]:
    return dict(Counter(f"ruff:{v['code']}" for v in violations if v.get("code")))


def _group_ruff_by_file(violations: list[dict], root: Path | None = None) -> dict[str, int]:
    from ratchet_check import ROOT  # noqa: F401,E402

    root = ROOT if root is None else root
    return dict(Counter(Path(v["filename"]).relative_to(root).as_posix() for v in violations if v.get("filename")))


def _parse_mypy_records(output: str) -> list[tuple[str, str]]:
    from ratchet_check import MYPY_CODED_ERROR_RE, MYPY_UNCODED_ERROR_RE

    records: list[tuple[str, str]] = []
    for line in output.splitlines():
        coded = MYPY_CODED_ERROR_RE.search(line)
        if coded:
            records.append((line.split(":", 1)[0], coded.group(1)))
        elif MYPY_UNCODED_ERROR_RE.search(line):
            records.append((line.split(":", 1)[0], "uncoded"))
    return records


def mypy_run(root: Path | None = None) -> list[tuple[str, str]]:
    from ratchet_check import ROOT, TARGET, run_output

    root = ROOT if root is None else root
    output = run_output("mypy", "--config-file", str(root / "pyproject.toml"), ".", cwd=root / TARGET)
    return _parse_mypy_records(output)


def _group_mypy_by_rule(records: list[tuple[str, str]]) -> dict[str, int]:
    return dict(Counter(f"mypy:{code}" for _file, code in records))


def _group_mypy_by_file(records: list[tuple[str, str]]) -> dict[str, int]:
    from ratchet_check import TARGET  # noqa: F401,E402

    return dict(Counter(f"{TARGET}/{file}" for file, _code in records))


def _parse_xenon_json(stdout: str) -> dict:
    try:
        return json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return {}


def xenon_run(root: Path | None = None) -> dict:
    from ratchet_check import ROOT, TARGET, run

    root = ROOT if root is None else root
    stdout = run("radon", "cc", TARGET, "-j", "-i", "tests,archive_not_used_trash", "--show-closures", cwd=root)
    return _parse_xenon_json(stdout)


def _xenon_total(data: dict, max_absolute: str | None = None) -> int:
    from ratchet_check import COMPLEXITY_RANKS, XENON_MAX_ABSOLUTE

    max_absolute = XENON_MAX_ABSOLUTE if max_absolute is None else max_absolute
    threshold = COMPLEXITY_RANKS.index(max_absolute)
    return sum(
        1 for blocks in data.values() for block in blocks if COMPLEXITY_RANKS.index(block.get("rank", "A")) > threshold
    )


def _group_xenon_by_file(data: dict, max_absolute: str | None = None) -> dict[str, int]:
    from ratchet_check import COMPLEXITY_RANKS, XENON_MAX_ABSOLUTE

    max_absolute = XENON_MAX_ABSOLUTE if max_absolute is None else max_absolute
    threshold = COMPLEXITY_RANKS.index(max_absolute)
    result: dict[str, int] = {}
    for file_path, blocks in data.items():
        count = sum(1 for block in blocks if COMPLEXITY_RANKS.index(block.get("rank", "A")) > threshold)
        if count:
            result[file_path] = count
    return result


def loc_line_counts(root: Path | None = None) -> dict[str, int]:
    from ratchet_check import ROOT, TARGET, _line_count

    root = ROOT if root is None else root
    counts: dict[str, int] = {}
    for path in (root / TARGET).rglob("*.py"):
        if "__pycache__" in path.parts or "archive_not_used_trash" in path.parts:
            continue
        counts[path.relative_to(root).as_posix()] = _line_count(path)
    return counts


def loc_excess_total(line_counts: dict[str, int], max_lines: int = 300) -> int:
    return sum(max(0, n - max_lines) for n in line_counts.values())


def _run_current_analyzers() -> tuple[list[dict], list[tuple[str, str]], dict, dict[str, int]]:
    from ratchet_check import loc_line_counts, mypy_run, ruff_run, xenon_run

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="ratchet") as executor:
        ruff_future = executor.submit(ruff_run)
        mypy_future = executor.submit(mypy_run)
        xenon_future = executor.submit(xenon_run)
        loc_future = executor.submit(loc_line_counts)
        return ruff_future.result(), mypy_future.result(), xenon_future.result(), loc_future.result()


def _run_current_and_before_analyzers(
    before_root: Path,
) -> tuple[list[dict], list[tuple[str, str]], dict, dict[str, int], dict[str, dict[str, int]]]:
    from ratchet_check import (
        _group_mypy_by_file,
        _group_ruff_by_file,
        _group_xenon_by_file,
        loc_line_counts,
        mypy_run,
        ruff_run,
        xenon_run,
    )

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
