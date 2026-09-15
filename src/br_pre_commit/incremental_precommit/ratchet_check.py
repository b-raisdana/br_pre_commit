# print is the intended user-facing output for this pre-commit hook script
# See README.md: "design" for the module-level overview.
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(os.environ.get("BR_PRE_COMMIT_REPO_ROOT", Path.cwd())).resolve()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from precommit_config import (  # noqa: E402
    classify_hooks,
    enabled_pre_commit_hook_ids,
    ratchet_settings,
    unknown_hook_policy,
)

BASELINE_DIR = ROOT / ".br-pre-commit" / "ratchet"
BASELINE_GLOB = "baseline*.json"
_SETTINGS = ratchet_settings(ROOT)
TARGET = str(_SETTINGS["target"])
COMPLEXITY_RANKS = str(_SETTINGS["complexity-ranks"])
LOC_MAX_LINES = int(_SETTINGS["max-lines"])
LOC_SLACK = int(_SETTINGS["line-growth-slack"])
XENON_MAX_ABSOLUTE = str(_SETTINGS["xenon-max-absolute"])

MYPY_CODED_ERROR_RE = re.compile(r": error: .*\[([\w-]+)\]\s*$")
MYPY_UNCODED_ERROR_RE = re.compile(r": error: ")


def load_json(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        log.exception(
            f"load_json json.loads({path}.read_text()) failed with JSONDecodeError:" + str(e),
        )
        raise e
    except Exception as e:
        log.exception(
            f"load_json json.loads({path}.read_text()) failed Generally:" + str(e),
        )
        raise e


def find_baseline_files() -> list[Path]:
    return sorted(BASELINE_DIR.glob(BASELINE_GLOB))


def merge_baselines(baselines: list[dict[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for baseline in baselines:
        for key, value in baseline.items():
            if key not in merged:
                merged[key] = value
            else:
                merged[key] = min(merged[key], value)
    return dict(sorted(merged.items()))


def compute_new_baseline(old_baseline: dict[str, int], current_counts: dict[str, int]) -> dict[str, int]:
    result: dict[str, int] = {}
    for key in set(old_baseline) | set(current_counts):
        old_val = old_baseline.get(key, float("inf"))
        current_val = current_counts.get(key, 0)
        result[key] = int(min(old_val, current_val))
    return dict(sorted(result.items()))


def baseline_content_hash(baseline: dict[str, int]) -> str:
    content = json.dumps(baseline, indent=2, sort_keys=True) + "\n"
    return hashlib.sha256(content.encode()).hexdigest()[:8]


def baseline_filename(baseline: dict[str, int]) -> str:
    return f"baseline_{baseline_content_hash(baseline)}.json"


def write_baseline_file(baseline: dict[str, int]) -> Path:
    path = BASELINE_DIR / baseline_filename(baseline)
    path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
    subprocess.run(["git", "add", str(path)], cwd=ROOT, check=False)
    return path


def load_and_consolidate_baselines() -> dict[str, int]:
    files = find_baseline_files()
    if not files:
        return {}
    baselines = [load_json(f) for f in files]
    merged = merge_baselines(baselines)
    if len(files) > 1:
        for f in files:
            f.unlink()
        write_baseline_file(merged)
        for f in files:
            subprocess.run(["git", "add", "--", str(f)], cwd=ROOT, check=False)
    return merged


def run(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    return result.stdout


def run_output(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    return result.stdout + result.stderr


def _tool_of(key: str) -> str:
    return key.split(":", 1)[0]


def _exclude_tests(paths: list[Path]) -> list[Path]:
    return [path for path in paths if "tests" not in path.parts and "archive_not_used_trash" not in path.parts]


def _line_count(path: Path) -> int:
    return sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))


def _head_line_count(relpath: str) -> int | None:
    result = subprocess.run(["git", "show", f"HEAD:{relpath}"], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    return len(result.stdout.splitlines())


@dataclass(frozen=True)
class TouchedFile:
    path: Path
    is_new: bool
    old_path: Path | None


def touched_app_python_files() -> list[TouchedFile]:
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
        if "archive_not_used_trash" in new_path.parts:
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
        ["git", "worktree", "remove", "--force", str(worktree)], cwd=ROOT, capture_output=True, text=True, check=False
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
    blocked: list[tuple[str, Path, int, int]] = []
    for touched_file in touched:
        key = touched_file.path.as_posix()
        before_key = (touched_file.old_path or touched_file.path).as_posix()
        blocked.extend(_tool_regressions(touched_file, key, before_key, after_by_file, before_by_file))
        loc_regression = _loc_regression(touched_file, before_key)
        if loc_regression is not None:
            blocked.append(loc_regression)
    return blocked


def _validate_configured_hooks() -> list[str]:
    hook_ids = enabled_pre_commit_hook_ids(ROOT / ".pre-commit-config.yaml")
    _, unknown = classify_hooks(hook_ids, policy=unknown_hook_policy(ROOT))
    return unknown


def characterization_test_touched() -> bool:
    stdout = run("git", "diff", "--cached", "--name-only")
    test_dirs = ("app/tests/characterization", "app/tests/unit", "app/tests/regression")
    return any(line.startswith(test_dirs) for line in stdout.splitlines())


from ratchet_check_tools import *  # noqa: F403,E402


def main() -> int:
    from ratchet_check_main import main as _main  # noqa: F402,E402

    return _main()


if __name__ == "__main__":
    sys.exit(main())
