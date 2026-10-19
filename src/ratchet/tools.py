"""Tool runners and analyzers for the incremental pre-commit ratchet.

Runs linters (ruff, mypy, radon/xenon) and LOC counter, both on current HEAD and
on the before state (via git worktree). Groups results by rule code and by file.
This module is stateless — it only runs tools and returns structured data.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

from ..helper.paths import get_pyproject_toml_path, get_user_repo_path_from_env
from .common import RuffViolation, XenonData, count_lines, output_run, path_matches_with_regex, run
from .config import ratchet_config

type AnalyzerOutput = list[RuffViolation] | list[tuple[str, str]] | XenonData | dict[str, int]


def _parse_ruff_json(stdout: str) -> list[RuffViolation]:
    try:
        return cast(list[RuffViolation], json.loads(stdout or "[]"))
    except json.JSONDecodeError:
        return []


def ruff_run(user_repo_root: Path | None = None) -> list[RuffViolation]:
    user_repo_root = user_repo_root or get_user_repo_path_from_env()
    stdout = run("ruff", "check", str(ratchet_config.target_dir_rel_path), "--output-format=json", cwd=user_repo_root)
    return _parse_ruff_json(stdout)


def _group_ruff_by_rule(violations: list[RuffViolation]) -> dict[str, int]:
    return dict(Counter(f"ruff:{violation['code']}" for violation in violations if violation.get("code")))


def _group_ruff_by_file(violations: list[RuffViolation], user_repo_root: Path | None = None) -> dict[str, int]:
    user_repo_root = user_repo_root or get_user_repo_path_from_env()
    return dict(
        Counter(
            Path(violation["filename"]).relative_to(user_repo_root).as_posix()
            for violation in violations
            if violation.get("filename")
        )
    )


def _parse_mypy_records(output: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for line in output.splitlines():
        coded = re.compile(ratchet_config.mypy_coded_error_re).search(line)
        if coded:
            records.append((line.split(":", 1)[0], coded.group(1)))
        elif re.compile(ratchet_config.mypy_uncoded_error_re).search(line):
            records.append((line.split(":", 1)[0], "uncoded"))
    return records


def mypy_run(user_repo_root: Path | None = None) -> list[tuple[str, str]]:
    user_repo_root = user_repo_root or get_user_repo_path_from_env()
    output = output_run(
        "mypy",
        "--config-file",
        str(get_pyproject_toml_path()),  # str(user_repo_root / "pyproject.toml"),
        ".",
        cwd=user_repo_root / ratchet_config.target_dir_rel_path,
    )
    return _parse_mypy_records(output)


def _group_mypy_by_rule(records: list[tuple[str, str]]) -> dict[str, int]:
    return dict(Counter(f"mypy:{code}" for _file, code in records))


def _group_mypy_by_file(records: list[tuple[str, str]]) -> dict[str, int]:
    return dict(Counter(f"{ratchet_config.target_dir_rel_path}/{file}" for file, _code in records))


def _parse_xenon_json(stdout: str) -> XenonData:
    try:
        return cast(XenonData, json.loads(stdout or "{}"))
    except json.JSONDecodeError:
        return {}


def xenon_run(user_repo_root: Path | None = None) -> XenonData:
    user_repo_root = user_repo_root or get_user_repo_path_from_env()
    exclude_dirs = ",".join(ratchet_config.exclude_dirs)
    stdout = run(
        "radon",
        "cc",
        str(ratchet_config.target_dir_rel_path),
        "-j",
        "-i",
        f"tests,{exclude_dirs}",
        "--show-closures",
        cwd=user_repo_root,
    )
    return _parse_xenon_json(stdout)


def _xenon_total(data: XenonData, max_absolute: str | None = None) -> int:
    max_absolute = ratchet_config.xenon_max_absolute if max_absolute is None else max_absolute
    threshold = ratchet_config.xenon_complexity_ranks.index(max_absolute)
    return sum(
        1
        for blocks in data.values()
        for block in blocks
        if ratchet_config.xenon_complexity_ranks.index(block.get("rank") or "A") > threshold
    )


def _group_xenon_by_file(data: XenonData, max_absolute: str | None = None) -> dict[str, int]:
    max_absolute = ratchet_config.xenon_max_absolute if max_absolute is None else max_absolute
    threshold = ratchet_config.xenon_complexity_ranks.index(max_absolute)
    result: dict[str, int] = {}
    for file_path, blocks in data.items():
        count = sum(
            1 for block in blocks if ratchet_config.xenon_complexity_ranks.index(block.get("rank") or "A") > threshold
        )
        if count:
            result[file_path] = count
    return result


def loc_line_counts(user_repo_root: Path | None = None) -> dict[str, int]:
    user_repo_root = user_repo_root or get_user_repo_path_from_env()
    counts: dict[str, int] = {}
    for path in (user_repo_root / ratchet_config.target_dir_rel_path).rglob("*.py"):
        if "__pycache__" in path.parts or path_matches_with_regex(path, ratchet_config.exclude_dir_regex):
            continue
        counts[path.relative_to(user_repo_root).as_posix()] = count_lines(path)
    return counts


def _exclude_tests(paths: list[Path]) -> list[Path]:
    """Drop any path that lives under a tests directory."""
    return [path for path in paths if "tests" not in path.parts]


def loc_excess_total(line_counts: dict[str, int], max_lines: int = 300) -> int:
    return sum(max(0, n - max_lines) for n in line_counts.values())


def _run_analyzers(
    jobs: dict[str, Callable[[], AnalyzerOutput]],
    *,
    workers: int,
    thread_name_prefix: str,
) -> dict[str, AnalyzerOutput]:
    """Start analyzer jobs together and return their results under stable names."""
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=thread_name_prefix) as executor:
        futures = {name: executor.submit(job) for name, job in jobs.items()}
        return {name: future.result() for name, future in futures.items()}


def run_current_analyzers() -> tuple[list[RuffViolation], list[tuple[str, str]], XenonData, dict[str, int]]:
    results = _run_analyzers(
        {"ruff": ruff_run, "mypy": mypy_run, "xenon": xenon_run, "loc": loc_line_counts},
        workers=4,
        thread_name_prefix="ratchet",
    )
    return cast(
        tuple[list[RuffViolation], list[tuple[str, str]], XenonData, dict[str, int]],
        (results["ruff"], results["mypy"], results["xenon"], results["loc"]),
    )


def _run_current_and_before_analyzers(
    before_user_repo_root: Path,
) -> tuple[
    list[RuffViolation],
    list[tuple[str, str]],
    XenonData,
    dict[str, int],
    dict[str, dict[str, int]],
]:
    results = _run_analyzers(
        {
            "ruff": ruff_run,
            "mypy": mypy_run,
            "xenon": xenon_run,
            "loc": loc_line_counts,
            "before_ruff": lambda: ruff_run(before_user_repo_root),
            "before_mypy": lambda: mypy_run(before_user_repo_root),
            "before_xenon": lambda: xenon_run(before_user_repo_root),
        },
        workers=7,
        thread_name_prefix="ratchet-all",
    )
    ruff_violations = results["ruff"]
    mypy_records = results["mypy"]
    xenon_data = results["xenon"]
    loc_counts = results["loc"]
    before_by_file = {
        "mypy": _group_mypy_by_file(cast(list[tuple[str, str]], results["before_mypy"])),
        "ruff": _group_ruff_by_file(
            cast(list[RuffViolation], results["before_ruff"]), user_repo_root=before_user_repo_root
        ),
        "xenon": _group_xenon_by_file(cast(XenonData, results["before_xenon"])),
    }
    return cast(
        tuple[
            list[RuffViolation],
            list[tuple[str, str]],
            XenonData,
            dict[str, int],
            dict[str, dict[str, int]],
        ],
        (ruff_violations, mypy_records, xenon_data, loc_counts, before_by_file),
    )
