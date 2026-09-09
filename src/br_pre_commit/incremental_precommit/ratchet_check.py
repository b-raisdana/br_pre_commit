# print is the intended user-facing output for this pre-commit hook script
# See README.md: "design" for the module-level overview.
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

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

MYPY_CODED_ERROR_RE = re.compile(r": error: .*\[([\w-]+)\]\s*$")
MYPY_UNCODED_ERROR_RE = re.compile(r": error: ")


def load_json(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


# ---- multi-file baseline management: merge, hash-based names, consolidation ----


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


# ---- ruff: raw run + two groupings of the same violations ----


def _parse_ruff_json(stdout: str) -> list[dict]:
    try:
        return json.loads(stdout or "[]")
    except json.JSONDecodeError:
        return []


def ruff_run(root: Path = ROOT) -> list[dict]:
    stdout = run("ruff", "check", TARGET, "--output-format=json", cwd=root)
    return _parse_ruff_json(stdout)


def _group_ruff_by_rule(violations: list[dict]) -> dict[str, int]:
    return dict(Counter(f"ruff:{v['code']}" for v in violations if v.get("code")))


def _group_ruff_by_file(violations: list[dict], root: Path | None = None) -> dict[str, int]:
    # ruff's "filename" is always absolute, unlike mypy's/radon's cwd-relative paths.
    root = ROOT if root is None else root
    return dict(Counter(Path(v["filename"]).relative_to(root).as_posix() for v in violations if v.get("filename")))


# ---- mypy: raw run + two groupings of the same (file, code) records ----


def _parse_mypy_records(output: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for line in output.splitlines():
        coded = MYPY_CODED_ERROR_RE.search(line)
        if coded:
            records.append((line.split(":", 1)[0], coded.group(1)))
        elif MYPY_UNCODED_ERROR_RE.search(line):
            records.append((line.split(":", 1)[0], "uncoded"))
    return records


def mypy_run(root: Path = ROOT) -> list[tuple[str, str]]:
    # See README.md: "mypy_count cwd choice"
    output = run_output("mypy", "--config-file", str(root / "pyproject.toml"), ".", cwd=root / TARGET)
    return _parse_mypy_records(output)


def _group_mypy_by_rule(records: list[tuple[str, str]]) -> dict[str, int]:
    return dict(Counter(f"mypy:{code}" for _file, code in records))


def _group_mypy_by_file(records: list[tuple[str, str]]) -> dict[str, int]:
    return dict(Counter(f"{TARGET}/{file}" for file, _code in records))


# ---- xenon: raw run + total / per-file views of the same radon data ----


def _parse_xenon_json(stdout: str) -> dict:
    try:
        return json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return {}


def xenon_run(root: Path = ROOT) -> dict:
    # See README.md: "xenon excludes tests and archive"
    stdout = run("radon", "cc", TARGET, "-j", "-i", "tests,archive_not_used_trash", "--show-closures", cwd=root)
    return _parse_xenon_json(stdout)


def _xenon_total(data: dict, max_absolute: str = "B") -> int:
    threshold = COMPLEXITY_RANKS.index(max_absolute)
    return sum(
        1 for blocks in data.values() for block in blocks if COMPLEXITY_RANKS.index(block.get("rank", "A")) > threshold
    )


def _group_xenon_by_file(data: dict, max_absolute: str = "B") -> dict[str, int]:
    threshold = COMPLEXITY_RANKS.index(max_absolute)
    result: dict[str, int] = {}
    for file_path, blocks in data.items():
        count = sum(1 for block in blocks if COMPLEXITY_RANKS.index(block.get("rank", "A")) > threshold)
        if count:
            result[file_path] = count
    return result


# ---- loc: raw per-file line counts, project total derived from them ----


def loc_line_counts(root: Path = ROOT) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in (root / TARGET).rglob("*.py"):
        if "__pycache__" in path.parts or "archive_not_used_trash" in path.parts:
            continue
        counts[path.relative_to(root).as_posix()] = _line_count(path)
    return counts


def loc_excess_total(line_counts: dict[str, int], max_lines: int = LOC_MAX_LINES) -> int:
    return sum(max(0, n - max_lines) for n in line_counts.values())


def _head_line_count(relpath: str) -> int | None:
    result = subprocess.run(["git", "show", f"HEAD:{relpath}"], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    return len(result.stdout.splitlines())


# ---- which files this commit touches, with rename tracking for the before/after diff ----


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


# ---- the blocking gate: per-touched-file before/after, not the project-wide total ----


def evaluate_file_gate(
    touched: list[TouchedFile],
    after_by_file: dict[str, dict[str, int]],
    before_by_file: dict[str, dict[str, int]],
) -> list[tuple[str, Path, int, int]]:
    blocked: list[tuple[str, Path, int, int]] = []
    for touched_file in touched:
        key = touched_file.path.as_posix()
        before_key = (touched_file.old_path or touched_file.path).as_posix()
        for tool in ("mypy", "ruff", "xenon"):
            after = after_by_file[tool].get(key, 0)
            before = 0 if touched_file.is_new else before_by_file[tool].get(before_key, 0)
            if after > before:
                blocked.append((tool, touched_file.path, before, after))

        after_lines = _line_count(ROOT / touched_file.path)
        if touched_file.is_new:
            if after_lines > LOC_MAX_LINES:
                blocked.append(("loc-new-file", touched_file.path, 0, after_lines))
        else:
            before_lines = _head_line_count(before_key)
            # scoped to files already over the cap - a file crossing the cap for the first time
            # in this commit isn't blocked here, only the (non-blocking) project-wide sum notices it
            if before_lines is not None and before_lines > LOC_MAX_LINES and after_lines > before_lines + LOC_SLACK:
                blocked.append(("loc", touched_file.path, before_lines, after_lines))
    return blocked


def print_ruff_details(paths: list[Path]) -> None:
    if not paths:
        print("    no files to inspect")
        return
    output = run_output("ruff", "check", *(path.as_posix() for path in paths))
    print(output.rstrip() or "    ruff reported no errors on these files")


def print_mypy_details(paths: list[Path]) -> None:
    app_paths = [path.relative_to(TARGET).as_posix() for path in paths]
    if not app_paths:
        print("    no files to inspect")
        return
    output = run_output("mypy", "--config-file", str(ROOT / "pyproject.toml"), *app_paths, cwd=ROOT / TARGET)
    print(output.rstrip() or "    mypy reported no errors on these files")


def print_xenon_details(paths: list[Path], max_absolute: str = "B") -> None:
    paths = _exclude_tests(paths)
    if not paths:
        print("    no files to inspect")
        return
    stdout = run("radon", "cc", "-j", "--show-closures", *(path.as_posix() for path in paths))
    data = _parse_xenon_json(stdout)
    threshold = COMPLEXITY_RANKS.index(max_absolute)
    printed = False
    for file_path, blocks in sorted(data.items()):
        for block in blocks:
            rank = block.get("rank", "A")
            if COMPLEXITY_RANKS.index(rank) <= threshold:
                continue
            print(f"    {file_path}:{block.get('lineno')} {block.get('type')} {block.get('name')} rank {rank}")
            printed = True
    if not printed:
        print("    xenon/radon reported no rank > B blocks on these files")


def print_loc_details(paths: list[Path], max_lines: int = LOC_MAX_LINES) -> None:
    for path in paths:
        print(f"    {path.as_posix()}: {_line_count(ROOT / path)} lines (cap {max_lines}, slack {LOC_SLACK})")


DETAIL_PRINTERS: dict[str, Callable[[list[Path]], None]] = {
    "ruff": print_ruff_details,
    "mypy": print_mypy_details,
    "xenon": print_xenon_details,
    "loc": print_loc_details,
}


def _run_current_analyzers() -> tuple[list[dict], list[tuple[str, str]], dict, dict[str, int]]:
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="ratchet") as executor:
        ruff_future = executor.submit(ruff_run)
        mypy_future = executor.submit(mypy_run)
        xenon_future = executor.submit(xenon_run)
        loc_future = executor.submit(loc_line_counts)
        return ruff_future.result(), mypy_future.result(), xenon_future.result(), loc_future.result()


def _run_current_and_before_analyzers(
    before_root: Path,
) -> tuple[list[dict], list[tuple[str, str]], dict, dict[str, int], dict[str, dict[str, int]]]:
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


def _validate_configured_hooks() -> list[str]:
    hook_ids = enabled_pre_commit_hook_ids(ROOT / ".pre-commit-config.yaml")
    _, unknown = classify_hooks(hook_ids, policy=unknown_hook_policy(ROOT))
    return unknown


def characterization_test_touched() -> bool:
    stdout = run("git", "diff", "--cached", "--name-only")
    test_dirs = ("app/tests/characterization", "app/tests/unit", "app/tests/regression")
    return any(line.startswith(test_dirs) for line in stdout.splitlines())


def main() -> int:
    unknown = _validate_configured_hooks()
    if unknown:
        print(f"Incremental pre-commit ratchet: warning: unregistered hook(s): {', '.join(unknown)}")
    old_baseline = load_and_consolidate_baselines()

    touched = touched_app_python_files()
    worktree = _head_worktree() if touched else None
    before_by_file = {"mypy": {}, "ruff": {}, "xenon": {}}
    try:
        if worktree is None:
            ruff_violations, mypy_records, xenon_data, loc_counts = _run_current_analyzers()
        else:
            ruff_violations, mypy_records, xenon_data, loc_counts, before_by_file = _run_current_and_before_analyzers(
                worktree
            )
    finally:
        if worktree is not None:
            _remove_worktree(worktree)

    current_counts: dict[str, int] = {
        **_group_ruff_by_rule(ruff_violations),
        **_group_mypy_by_rule(mypy_records),
        "xenon": _xenon_total(xenon_data),
        "loc": loc_excess_total(loc_counts),
    }

    regressed_trend: list[tuple[str, int, int]] = []
    improved: list[tuple[str, int, int]] = []
    for key in sorted(set(old_baseline) | set(current_counts)):
        current = current_counts.get(key, 0)
        base = old_baseline.get(key)
        if base is None:
            print(f"[{key}] no baseline yet - bootstrapping at {current}")
        elif current > base:
            regressed_trend.append((key, base, current))
        elif current < base:
            improved.append((key, base, current))

    file_gate_blocked: list[tuple[str, Path, int, int]] = []
    if touched:
        after_by_file = {
            "mypy": _group_mypy_by_file(mypy_records),
            "ruff": _group_ruff_by_file(ruff_violations),
            "xenon": _group_xenon_by_file(xenon_data),
        }
        file_gate_blocked = evaluate_file_gate(touched, after_by_file, before_by_file)

    if file_gate_blocked:
        print("Incremental pre-commit ratchet: BLOCKED - a touched file got worse\n")
        blocked_paths: set[Path] = set()
        for tool, path, before, after in file_gate_blocked:
            print(f"  {tool} in {path.as_posix()}: {before} -> {after}")
            blocked_paths.add(path)
        print("\nDetails:")
        printed_tools: set[str] = set()
        for tool, _path, _before, _after in file_gate_blocked:
            base_tool = "loc" if tool.startswith("loc") else tool
            if base_tool in printed_tools:
                continue
            printed_tools.add(base_tool)
            print(f"\n  {base_tool}:")
            DETAIL_PRINTERS[base_tool](sorted(blocked_paths))
        print(
            f"\nEach touched file is checked against its own pre-commit state (new files against a zero "
            f"baseline, and a {LOC_MAX_LINES}-line cap for loc). mypy/ruff/xenon allow zero increase; loc "
            f"allows a {LOC_SLACK}-line slack. An oversized file can be split into two+ files to fit under "
            "the loc cap - that's a legitimate way through this gate, but a meaningful split, not "
            "arbitrary chopping to dodge the check."
        )
        return 1

    new_baseline = compute_new_baseline(old_baseline, current_counts)
    if new_baseline != old_baseline:
        write_baseline_file(new_baseline)

    if regressed_trend:
        print("Incremental pre-commit ratchet: project-wide count rose (trend only, does not block)\n")
        for key, base, current in regressed_trend:
            print(f"  {key}: baseline {base} -> now {current} (+{current - base}); no touched file regressed")

    if improved:
        print("Incremental pre-commit ratchet: progress locked in\n")
        for key, base, current in improved:
            print(f"  {key}: baseline {base} -> {current} (-{base - current} fixed)")
        if not characterization_test_touched():
            print(
                "\nNote: this commit fixed pre-existing problems, but doesn't touch "
                "app/tests/{characterization,unit,regression}. If any of these were "
                "behavior-affecting fixes (not just type annotations/formatting), pin the before/after "
                "behavior with a characterization test first - see the test-strategy skill. This is a "
                "reminder, not a block: this repo's mutation-safety net is test discipline, not a mutation-testing "
                "tool (see docs/infrastructure.md#pre-commit)."
            )

    tool_totals: dict[str, int] = {"ruff": 0, "mypy": 0, "xenon": 0, "loc": 0}
    tool_baseline_totals: dict[str, int] = {"ruff": 0, "mypy": 0, "xenon": 0, "loc": 0}
    for key, count in current_counts.items():
        tool_totals[_tool_of(key)] = tool_totals.get(_tool_of(key), 0) + count
    for key, count in new_baseline.items():
        tool_baseline_totals[_tool_of(key)] = tool_baseline_totals.get(_tool_of(key), 0) + count

    print("\nIncremental pre-commit ratchet: OK (no touched file regressed)")
    for tool in sorted(set(tool_totals) | set(tool_baseline_totals)):
        print(f"  {tool}: {tool_totals.get(tool, 0)} / baseline {tool_baseline_totals.get(tool, 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
