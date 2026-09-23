"""Reporting and main orchestration for the pre-commit wrapper."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypedDict, cast

from helper.git import get_staged_files, git_cmd
from helper.paths import get_log_dir, get_log_file, get_user_repo_path_from_env

if TYPE_CHECKING:
    from .__main__ import JobResult


class ResultWithOutput(Protocol):
    @property
    def stdout(self) -> str: ...


class RuffLocation(TypedDict):
    row: int


class RuffViolation(TypedDict):
    filename: str
    location: RuffLocation
    code: str
    message: str


class LintWarning(TypedDict):
    file: str
    line: int
    code: str
    message: str


class SummaryEntry(TypedDict, total=False):
    timestamp: str
    branch: str
    staged_files: list[str]
    result: str
    jobs: dict[str, int]
    advisory_lint_warnings: list[LintWarning]
    report: str
    snapshot_dir: str


def _parse_ruff_warnings(ruff_result: ResultWithOutput, rebase_root: Path) -> list[LintWarning]:
    warnings: list[LintWarning] = []
    try:
        violations = cast(list[RuffViolation], json.loads(ruff_result.stdout or "[]"))
    except (AttributeError, json.JSONDecodeError):
        return warnings
    for violation in violations:
        warnings.append(
            {
                "file": Path(violation["filename"]).resolve().relative_to(rebase_root).as_posix(),
                "line": violation["location"]["row"],
                "code": violation["code"],
                "message": violation["message"],
            }
        )
    return warnings


def _parse_radon_warnings(radon_result: ResultWithOutput | None) -> list[LintWarning]:
    warnings: list[LintWarning] = []
    if radon_result is None or not radon_result.stdout:
        return warnings
    for line in radon_result.stdout.splitlines():
        line = line.strip()
        if not line or " - " not in line:
            continue
        try:
            file_part, score_part = line.split(" - ", 1)
            rank, score = score_part.split()
            warnings.append(
                LintWarning(
                    **{
                        "file": file_part.strip(),
                        "line": 0,
                        "code": f"radon-mi-{rank}",
                        "message": f"Maintainability Index: {score.strip('()')} ({rank})",
                    }
                )
            )
        except (IndexError, ValueError):
            continue
    return warnings


def _advisory_warnings(results: list[JobResult]) -> list[LintWarning]:
    warnings: list[LintWarning] = []
    ruff_result = next((item for item in results if getattr(item, "job_id", None) == "advisory-ruff"), None)
    if ruff_result is not None:
        warnings.extend(_parse_ruff_warnings(ruff_result, get_user_repo_path_from_env()))

    radon_result = next((item for item in results if getattr(item, "job_id", None) == "advisory-radon"), None)
    warnings.extend(_parse_radon_warnings(radon_result))
    return warnings


def _write_report(human_ts: str, results: list[JobResult]) -> Path:
    report_dir = get_log_dir() / "pre-commit-runs"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{human_ts}.log"
    sections = [
        f"## {result.job_id}\nstatus: {'pass' if result.returncode == 0 else 'fail'}\n"
        f"exit: {result.returncode}\nduration_seconds: {result.duration_seconds:.3f}\n"
        f"command: {' '.join(result.command)}\n\nstdout:\n{result.stdout}\n\nstderr:\n{result.stderr}\n"
        for result in results
    ]
    temporary_path = report_path.with_suffix(".tmp")
    temporary_path.write_text("\n".join(sections), encoding="utf-8")
    temporary_path.replace(report_path)
    return report_path


def _append_summary(entry: SummaryEntry) -> None:
    get_log_dir().mkdir(parents=True, exist_ok=True)
    with get_log_file().open("a", encoding="utf-8") as output:
        output.write(json.dumps(entry) + "\n")


def _run_branch_protection(branch: str) -> list[JobResult]:
    from .__main__ import JobResult, _branch_protection_result  # noqa: F402,E402

    try:
        result = _branch_protection_result(branch)
    except ValueError as exc:
        message = f"configuration error: {exc}"
        sys.stdout.write(message + "\n")
        return [JobResult("configuration", (), 2, 0.0, "", message)]
    if result is None:
        return []
    sys.stdout.write(result.stderr + "\n")
    return [result]


async def _run_pipeline(staged: list[str]) -> list[JobResult]:
    from .__main__ import JobResult, _run_hooks, _run_job  # noqa: F402,E402

    if not staged:
        sys.stdout.write("No staged files; running the standard pre-commit pipeline.\n")
        return [await _run_job("pre-commit", ["pre-commit", "run", "--hook-stage", "pre-commit"], asyncio.Lock())]
    try:
        from pre_commit.staged_files_only import staged_files_only
        from pre_commit.store import Store

        with staged_files_only(Store().directory):
            return await _run_hooks(staged)
    except ValueError as exc:
        message = f"configuration error: {exc}"
        sys.stdout.write(message + "\n")
        return [JobResult("configuration", (), 2, 0.0, "", message)]


def _write_summary(human_ts: str, results: list[JobResult]) -> tuple[Path, list[LintWarning]]:
    report_path = _write_report(human_ts, results)
    warnings = _advisory_warnings(results)
    for hit in warnings:
        sys.stdout.write(f"warning: {hit['file']}:{hit['line']} {hit['code']} {hit['message']}\n")
    return report_path, warnings


async def _main_async() -> int:
    from .__main__ import _run_backup
    from .hooks import pre_commit_hook_is_enabled

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    human_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
    branch = await git_cmd("rev-parse", "--abbrev-ref", "HEAD")
    staged = await get_staged_files()
    results = _run_branch_protection(branch) if pre_commit_hook_is_enabled("no-commit-to-main") else []
    if not results:
        results = await _run_pipeline(staged)

    passed = all(result.returncode == 0 for result in results if not result.job_id.startswith("advisory-"))
    snapshot_dir: str | None = None
    if not passed:
        backup_result, snapshot_dir = await _run_backup(asyncio.Lock())
        results.append(backup_result)

    report_path, warnings = _write_summary(human_ts, results)
    entry: SummaryEntry = {
        "timestamp": timestamp,
        "branch": branch,
        "staged_files": staged,
        "result": "pass" if passed else "fail",
        "jobs": {result.job_id: result.returncode for result in results},
        "advisory_lint_warnings": warnings,
        "report": report_path.relative_to(get_user_repo_path_from_env()).as_posix(),
    }
    if snapshot_dir is not None:
        entry["snapshot_dir"] = snapshot_dir
    _append_summary(entry)

    if not passed:
        _report_failure(report_path, snapshot_dir)
        return 1
    return 0


def _report_failure(report_path: Path, snapshot_dir: str | None) -> None:
    sys.stdout.write(f"Pre-commit failed; report: {report_path.relative_to(get_user_repo_path_from_env())}\n")
    if snapshot_dir:
        sys.stdout.write(f"Working state backed up to {snapshot_dir}\n")


def main() -> int:
    from .__main__ import log  # noqa: F402,E402

    try:
        return asyncio.run(_main_async())
    except KeyboardInterrupt as exc:
        log.error("Pre-commit wrapper terminated: %s", exc)
        return 1
