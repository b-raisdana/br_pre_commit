"""Per-file regression gate for the incremental pre-commit ratchet.

Evaluates whether any touched file has regressed relative to its pre-commit state.
New files are checked against a zero baseline (with LOC cap). Renamed files compare
against their old path at HEAD. This module is purely functional — it takes pre-computed
by-file violation counts and returns a list of regressions; it does not run tools.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .baseline import (  # noqa: F401,E402
    EXCLUDE_DIR,
    LOC_MAX_LINES,
    LOC_SLACK,
    ROOT,
    TARGET,
    _tool_of,
    run,
)


@dataclass(frozen=True)
class TouchedFile:
    path: Path
    is_new: bool
    old_path: Path | None


def touched_app_python_files() -> list[TouchedFile]:
    """Get staged Python files under TARGET, excluding the configured exclude directory."""
    stdout = run("git", "diff", "--cached", "--name-status", "-M", "--diff-filter=ACMR")
    result: list[TouchedFile] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        old_raw, new_raw = (parts[1], parts[2]) if status.startswith("R") else (parts[1], parts[1])
        new_path = Path(new_raw)
        if new_path.parts[:1] != (TARGET,) or new_path.suffix != ".py":
            continue
        if EXCLUDE_DIR in new_path.parts:
            continue
        if not (ROOT / new_path).exists():
            continue
        is_new = status.startswith("A")
        old_path = None if is_new else Path(old_raw)
        result.append(TouchedFile(path=new_path, is_new=is_new, old_path=old_path))
    return sorted(result, key=lambda t: t.path.as_posix())


def _head_worktree() -> Path | None:
    head = run("git", "rev-parse", "--verify", "HEAD").strip()
    if not head:
        return None
    tmp_dir = Path(tempfile.mkdtemp(prefix="ratchet-head-"))
    result = subprocess.run(
        ["git", "worktree", "add", "--detach", "--quiet", str(tmp_dir), "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return tmp_dir if result.returncode == 0 else None


def _remove_worktree(worktree: Path) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _tool_regressions(
    touched_file: TouchedFile,
    key: str,
    before_key: str,
    after_by_file: dict[str, dict[str, int]],
    before_by_file: dict[str, dict[str, int]],
) -> list[tuple[str, Path, int, int]]:
    blocked: list[tuple[str, Path, int, int]] = []
    for tool in ("mypy", "ruff", "xenon"):
        after = after_by_file[tool].get(key, 0)
        before = 0 if touched_file.is_new else before_by_file[tool].get(before_key, 0)
        if after > before:
            blocked.append((tool, touched_file.path, before, after))
    return blocked


def _loc_regression(touched_file: TouchedFile, before_key: str) -> tuple[str, Path, int, int] | None:
    from .baseline import _line_count  # noqa: F402,E402

    after_lines = _line_count(ROOT / touched_file.path)
    if touched_file.is_new:
        if after_lines > LOC_MAX_LINES:
            return "loc-new-file", touched_file.path, 0, after_lines
        return None
    before_lines = _head_line_count(before_key)
    if before_lines is not None and before_lines > LOC_MAX_LINES and after_lines > before_lines + LOC_SLACK:
        return "loc", touched_file.path, before_lines, after_lines
    return None


def evaluate_file_gate(
    touched: list[TouchedFile],
    after_by_file: dict[str, dict[str, int]],
    before_by_file: dict[str, dict[str, int]],
) -> list[tuple[str, Path, int, int]]:
    """Return list of (tool, path, before, after) for each regression on touched files."""
    blocked: list[tuple[str, Path, int, int]] = []
    for touched_file in touched:
        key = touched_file.path.as_posix()
        before_key = (touched_file.old_path or touched_file.path).as_posix()
        blocked.extend(_tool_regressions(touched_file, key, before_key, after_by_file, before_by_file))
        loc_regression = _loc_regression(touched_file, before_key)
        if loc_regression is not None:
            blocked.append(loc_regression)
    return blocked


def _head_line_count(relpath: str) -> int | None:
    result = subprocess.run(["git", "show", f"HEAD:{relpath}"], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    return len(result.stdout.splitlines())


def _validate_configured_hooks() -> list[str]:
    from precommit_wrapper.config import classify_hooks, enabled_pre_commit_hook_ids, unknown_hook_policy  # noqa: E402

    hook_ids = enabled_pre_commit_hook_ids(ROOT / ".pre-commit-config.yaml")
    result = classify_hooks(hook_ids, policy=unknown_hook_policy())
    unknown: list[str] = result[1]
    return unknown


def characterization_test_touched() -> bool:
    stdout = run("git", "diff", "--cached", "--name-only")
    test_dirs = ("app/tests/characterization", "app/tests/unit", "app/tests/regression")
    return any(line.startswith(test_dirs) for line in stdout.splitlines())
