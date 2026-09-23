"""Shared utilities for the incremental pre-commit ratchet.

Common functions used by both __main__.py and baseline.py to avoid circular imports
and code duplication.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from helper.paths import get_user_repo_path_from_env

from .config import RatchetConfig, ratchet_config


class RuffViolation(TypedDict):
    filename: str
    code: str


class XenonBlock(TypedDict, total=False):
    rank: str
    lineno: int
    type: str
    name: str


XenonData = dict[str, list[XenonBlock]]

log = logging.getLogger(__name__)

AnalyzerResult = tuple[list[RuffViolation], list[tuple[str, str]], XenonData, dict[str, int]]
AnalyzerResultWithBefore = tuple[
    list[RuffViolation],
    list[tuple[str, str]],
    XenonData,
    dict[str, int],
    dict[str, dict[str, int]],
]


@dataclass(frozen=True)
class TouchedFile:
    path: Path
    is_new: bool
    old_path: Path | None


def path_matches_with_regex(path: Path, regex: str) -> bool:
    """Return True when ``path`` lives under the configured exclude directory."""
    import re

    return bool(
        re.search(
            rf"(?:^|[/\\]){re.escape(regex)}(?:[/\\]|$)",
            str(path),
        )
    )


@dataclass
class RatchetConfigOverride:
    """Optional overrides for ratchet config."""

    target_dir_rel_path: Path | None = None
    loc_max_lines: int | None = None
    loc_line_growth_slack: int | None = None
    xenon_max_absolute: str | None = None
    xenon_complexity_ranks: str | None = None
    exclude_dir_regex: str | None = None
    exclude_dirs: list[str] | None = None

    def apply_to_config(self, config: RatchetConfig) -> RatchetConfig:
        """Apply defined overrides to config."""
        for key, value in vars(self).items():
            if value is not None:
                setattr(config, key, value)
        return config


def _tool_of(key: str) -> str:
    return key.split(":", 1)[0]


def count_lines(path: Path) -> int:
    return sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))


async def _async_line_count(path: Path) -> int:
    return await asyncio.to_thread(count_lines, path)


def load_json(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return {str(k): int(v) for k, v in data.items()}
    except json.JSONDecodeError as e:
        log.exception(f"load_json json.loads({path}.read_text()) failed with JSONDecodeError: {e}")
        raise
    except Exception as e:
        log.exception(f"load_json json.loads({path}.read_text()) failed: {e}")
        raise


async def async_load_json(path: Path) -> dict[str, int]:
    return await asyncio.to_thread(load_json, path)


async def async_find_baseline_files() -> list[Path]:
    return await asyncio.to_thread(find_baseline_files)


def merge_baselines(baselines: list[dict[str, int]]) -> dict[str, int]:
    """Merge multiple baselines: union of keys, minimum value kept."""
    merged: dict[str, int] = {}
    for baseline in baselines:
        for key, value in baseline.items():
            if key not in merged:
                merged[key] = value
            else:
                merged[key] = min(merged[key], value)
    return dict(sorted(merged.items()))


def compute_new_baseline(old_baseline: dict[str, int], current_counts: dict[str, int]) -> dict[str, int]:
    """Compute ratcheted baseline: for each key, keep the minimum of old and current."""
    result: dict[str, int] = {}
    for key in set(old_baseline) | set(current_counts):
        old_val = old_baseline.get(key, float("inf"))
        current_val = current_counts.get(key, 0)
        value = int(min(old_val, current_val))
        if value > 0:
            result[key] = value
    return dict(sorted(result.items()))


def baseline_content_hash(baseline: dict[str, int]) -> str:
    """SHA-256 of JSON-serialized baseline (sorted keys, indented), truncated to 8 hex chars."""
    content = json.dumps(baseline, indent=2, sort_keys=True) + "\n"
    return hashlib.sha256(content.encode()).hexdigest()[:8]


def baseline_filename(baseline: dict[str, int]) -> str:
    return f"baseline_{baseline_content_hash(baseline)}.json"


def write_baseline_file(baseline: dict[str, int]) -> None:  # -> Path:
    path = ratchet_config.baseline_dir / baseline_filename(baseline)
    content = json.dumps(baseline, indent=2, sort_keys=True)
    path.write_text(content + "\n")
    subprocess.run(["git", "add", str(path)], cwd=get_user_repo_path_from_env(), check=False)
    print(f"Baseline written to {path}: {content}")
    # return path
    # return f"Baseline written to {path}: {content}"


def find_baseline_files() -> list[Path]:
    from .config import ratchet_config

    return sorted(ratchet_config.baseline_dir.glob(ratchet_config.baseline_glob))


async def async_write_baseline_file(baseline: dict[str, int]) -> None:
    await asyncio.to_thread(write_baseline_file, baseline)
    pass


def load_and_consolidate_baselines() -> dict[str, int]:
    """Load all baseline files, merge them, and consolidate to a single file if >1 existed."""
    files = find_baseline_files()
    if not files:
        return {}
    baselines = [load_json(f) for f in files]
    merged = {k: v for k, v in merge_baselines(baselines).items() if v > 0}
    if len(files) > 1:
        merged = {key: value for key, value in merged.items() if value > 0}
        for f in files:
            f.unlink()
        write_baseline_file(merged)
        for f in files:
            subprocess.run(["git", "add", "--", str(f)], cwd=get_user_repo_path_from_env(), check=False)
    return merged


async def async_load_and_consolidate_baselines() -> dict[str, int]:
    return await asyncio.to_thread(load_and_consolidate_baselines)


def run(*args: str, cwd: Path | None = None) -> str:
    cwd = cwd or get_user_repo_path_from_env()
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    return result.stdout


async def async_run(*args: str, cwd: Path | None = None) -> str:
    return await asyncio.to_thread(run, *args, cwd=cwd)


def output_run(*args: str, cwd: Path | None = None) -> str:
    cwd = cwd or get_user_repo_path_from_env()
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    return result.stdout + result.stderr


async def async_output_run(*args: str, cwd: Path | None = None) -> str:
    return await asyncio.to_thread(output_run, *args, cwd=cwd)


def write_new_baseline(old_baseline: dict[str, int], new_baseline: dict[str, int]) -> None:
    if new_baseline == old_baseline:
        return
    write_baseline_file(new_baseline)


async def async_write_new_baseline(
    old_baseline: dict[str, int], new_baseline: dict[str, int], force: bool = False
) -> None:
    if not force and new_baseline == old_baseline:
        return
    await async_write_baseline_file(new_baseline)


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


def get_current_counts(
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


async def async_get_current_counts(
    ruff_violations: list[RuffViolation],
    mypy_records: list[tuple[str, str]],
    xenon_data: XenonData,
    loc_counts: dict[str, int],
) -> dict[str, int]:
    return await asyncio.to_thread(get_current_counts, ruff_violations, mypy_records, xenon_data, loc_counts)


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


async def async_collect_analyzer_results(
    touched: list[TouchedFile],
    head_worktree: Callable[[], Path | None],
    remove_worktree: Callable[[Path], None],
    current_analyzers: Callable[[], AnalyzerResult],
    current_and_before_analyzers: Callable[[Path], AnalyzerResultWithBefore],
) -> AnalyzerResultWithBefore:
    return await asyncio.to_thread(
        _collect_analyzer_results,
        touched,
        head_worktree,
        remove_worktree,
        current_analyzers,
        current_and_before_analyzers,
    )


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


class RatchetSettingsOverride:
    """Context manager for temporarily overriding ratchet settings."""

    def __init__(self, override: RatchetConfigOverride | None = None):
        self.override = override or RatchetConfigOverride()
        self._original_config = None

    def __enter__(self):
        self._original_config = {
            "target_dir_rel_path": ratchet_config.target_dir_rel_path,
            "loc_max_lines": ratchet_config.loc_max_lines,
            "loc_line_growth_slack": ratchet_config.loc_line_growth_slack,
            "xenon_max_absolute": ratchet_config.xenon_max_absolute,
            "xenon_complexity_ranks": ratchet_config.xenon_complexity_ranks,
            "exclude_dir_regex": ratchet_config.exclude_dir_regex,
            "exclude_dirs": ratchet_config.exclude_dirs.copy(),
        }
        self.override.apply_to_config(ratchet_config)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._original_config:
            ratchet_config.target_dir_rel_path = self._original_config["target_dir_rel_path"]
            ratchet_config.loc_max_lines = self._original_config["loc_max_lines"]
            ratchet_config.loc_line_growth_slack = self._original_config["loc_line_growth_slack"]
            ratchet_config.xenon_max_absolute = self._original_config["xenon_max_absolute"]
            ratchet_config.xenon_complexity_ranks = self._original_config["xenon_complexity_ranks"]
            ratchet_config.exclude_dir_regex = self._original_config["exclude_dir_regex"]
            ratchet_config.exclude_dirs = self._original_config["exclude_dirs"]


async def baseline_current_state(override: RatchetConfigOverride | None = None, force: bool = False) -> dict[str, int]:
    """Allow developers to baseline current state of code with optional config override.

    This function can be called directly by developers to generate a baseline
    from the current state of the codebase, with optional configuration overrides.
    """
    with RatchetSettingsOverride(override):
        old_baseline = await async_load_and_consolidate_baselines()
        from .tools import (  # noqa: F402,E402
            run_current_analyzers,
        )

        ruff_violations, mypy_records, xenon_data, loc_counts = run_current_analyzers()
        current_counts = await async_get_current_counts(ruff_violations, mypy_records, xenon_data, loc_counts)
        current_counts = {k: v for k, v in current_counts.items() if v > 0}
        new_baseline = compute_new_baseline(old_baseline, current_counts)
        await async_write_new_baseline(old_baseline, new_baseline, force)
        return new_baseline


def baseline_current_state_sync(
    override: RatchetConfigOverride | None = None,
) -> dict[str, int]:
    """Synchronous version of baseline_current_state."""
    with RatchetSettingsOverride(override):
        old_baseline = load_and_consolidate_baselines()
        from .tools import (  # noqa: F402,E402
            run_current_analyzers,
        )

        ruff_violations, mypy_records, xenon_data, loc_counts = run_current_analyzers()
        current_counts = get_current_counts(ruff_violations, mypy_records, xenon_data, loc_counts)
        current_counts = {k: v for k, v in current_counts.items() if v > 0}
        new_baseline = compute_new_baseline(old_baseline, current_counts)
        write_new_baseline(old_baseline, new_baseline)
        return new_baseline
