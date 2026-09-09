"""Run pre-commit hooks concurrently with live and per-hook final logs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pre_commit.staged_files_only import staged_files_only
from pre_commit.store import Store
from precommit_config import (
    classify_hooks,
    enabled_pre_commit_hook_ids,
    job_timeout_seconds,
    protected_branches,
    unknown_hook_policy,
)

REPO_ROOT = Path(os.environ.get("BR_PRE_COMMIT_REPO_ROOT", Path.cwd())).resolve()
TOOL_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = REPO_ROOT / "logs" / "pre-commit"
LOG_FILE = LOG_DIR / "pre-commit.log"
CONFIG_PATH = REPO_ROOT / ".pre-commit-config.yaml"
ADVISORY_RUFF_RULES = "Q,RUF,T10,T20,ERA"

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
log = logging.getLogger("pre-commit-wrapper")


@dataclass(frozen=True)
class JobResult:
    job_id: str
    command: tuple[str, ...]
    returncode: int
    duration_seconds: float
    stdout: str
    stderr: str


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _staged_files() -> list[str]:
    output = _git("diff", "--cached", "--name-only")
    return output.splitlines() if output else []


def _branch_protection_result(branch: str) -> JobResult | None:
    if branch not in protected_branches(REPO_ROOT):
        return None
    message = f"Direct commits to protected branch '{branch}' are not allowed. Create a feature branch."
    return JobResult("branch-protection", (), 1, 0.0, "", message)


async def _terminate_process_group(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        await asyncio.wait_for(proc.wait(), timeout=3)
    except ProcessLookupError:
        return
    except TimeoutError:
        os.killpg(proc.pid, signal.SIGKILL)
        await proc.wait()


async def _run_job(
    job_id: str,
    command: list[str],
    terminal_lock: asyncio.Lock,
    *,
    stream_output: bool = True,
    timeout_seconds: float | None = None,
) -> JobResult:
    loop = asyncio.get_running_loop()
    started = loop.time()
    async with terminal_lock:
        sys.stdout.write(f"[{job_id}] started\n")
        sys.stdout.flush()
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=REPO_ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            limit=1024 * 1024,
        )
    except OSError as exc:
        message = f"could not start: {exc}\n"
        async with terminal_lock:
            sys.stdout.write(f"[{job_id}:stderr] {message}")
            sys.stdout.flush()
        return JobResult(job_id, tuple(command), 127, loop.time() - started, "", message)
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    async def drain(reader: asyncio.StreamReader, parts: list[str], stream_name: str) -> None:
        while chunk := await reader.read(4096):
            text = chunk.decode("utf-8", errors="replace")
            parts.append(text)
            if stream_output:
                async with terminal_lock:
                    sys.stdout.write(f"[{job_id}:{stream_name}] {text}")
                    if not text.endswith("\n"):
                        sys.stdout.write("\n")
                    sys.stdout.flush()

    try:
        assert proc.stdout is not None and proc.stderr is not None
        stdout_task = asyncio.create_task(drain(proc.stdout, stdout_parts, "stdout"))
        stderr_task = asyncio.create_task(drain(proc.stderr, stderr_parts, "stderr"))
        try:
            returncode = await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
        except TimeoutError:
            await _terminate_process_group(proc)
            stderr_parts.append(f"timed out after {timeout_seconds:g}s\n")
            returncode = 124
        finally:
            await asyncio.gather(stdout_task, stderr_task)
    except asyncio.CancelledError:
        await _terminate_process_group(proc)
        await asyncio.gather(stdout_task, stderr_task)
        raise
    duration = loop.time() - started
    async with terminal_lock:
        sys.stdout.write(f"[{job_id}] finished ({returncode}) in {duration:.2f}s\n")
        sys.stdout.flush()
    return JobResult(job_id, tuple(command), returncode, duration, "".join(stdout_parts), "".join(stderr_parts))


def _hook_command(hook_id: str, staged: list[str]) -> list[str]:
    return ["pre-commit", "run", hook_id, "--hook-stage", "pre-commit", "--color", "always", "--files", *staged]


async def _run_hooks(staged: list[str]) -> list[JobResult]:
    policy = unknown_hook_policy(REPO_ROOT)
    timeout = job_timeout_seconds(REPO_ROOT)
    specs, unknown = classify_hooks(enabled_pre_commit_hook_ids(CONFIG_PATH), policy=policy)
    if unknown:
        sys.stdout.write(f"warning: unregistered hooks run serially: {', '.join(unknown)}\n")

    terminal_lock = asyncio.Lock()
    results: list[JobResult] = []
    for spec in (spec for spec in specs if spec.mutates_files):
        results.append(
            await _run_job(spec.hook_id, _hook_command(spec.hook_id, staged), terminal_lock, timeout_seconds=timeout)
        )

    jobs = [
        _run_job(spec.hook_id, _hook_command(spec.hook_id, staged), terminal_lock, timeout_seconds=timeout)
        for spec in specs
        if not spec.mutates_files
    ]
    py_files = [f for f in staged if f.startswith("app/") and f.endswith(".py") and (REPO_ROOT / f).exists()]
    if py_files:
        jobs.append(
            _run_job(
                "advisory-ruff",
                ["ruff", "check", "--select", ADVISORY_RUFF_RULES, "--output-format=json", *py_files],
                terminal_lock,
                stream_output=False,
                timeout_seconds=timeout,
            )
        )
    results.extend(await asyncio.gather(*jobs))
    return results


def _advisory_warnings(results: list[JobResult]) -> list[dict[str, object]]:
    result = next((item for item in results if item.job_id == "advisory-ruff"), None)
    if result is None:
        return []
    try:
        violations = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return [
        {
            "file": Path(v["filename"]).resolve().relative_to(REPO_ROOT).as_posix(),
            "line": v["location"]["row"],
            "code": v["code"],
            "message": v["message"],
        }
        for v in violations
    ]


def _write_report(human_ts: str, results: list[JobResult]) -> Path:
    report_dir = LOG_DIR / "pre-commit-runs"
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


def _append_summary(entry: dict[str, object]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as output:
        output.write(json.dumps(entry) + "\n")


async def _run_backup(terminal_lock: asyncio.Lock) -> tuple[JobResult, str | None]:
    result = await _run_job(
        "backup",
        [
            sys.executable,
            str(TOOL_ROOT / "src/br_pre_commit/backup.py"),
            "--repo",
            str(REPO_ROOT),
            "--print-manifest-json",
        ],
        terminal_lock,
        timeout_seconds=job_timeout_seconds(REPO_ROOT),
    )
    try:
        snapshot_dir = json.loads(result.stdout.splitlines()[-1])["snapshot_dir"] if result.returncode == 0 else None
    except (IndexError, KeyError, json.JSONDecodeError):
        snapshot_dir = None
    return result, snapshot_dir


async def _main_async() -> int:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    human_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    staged = _staged_files()

    try:
        branch_result = _branch_protection_result(branch)
    except ValueError as exc:
        branch_result = None
        message = f"configuration error: {exc}"
        sys.stdout.write(message + "\n")
        results = [JobResult("configuration", (), 2, 0.0, "", message)]
    else:
        results = []

    if branch_result is not None:
        sys.stdout.write(branch_result.stderr + "\n")
        results = [branch_result]
    elif results:
        pass
    elif not staged:
        sys.stdout.write("No staged files; running the standard pre-commit pipeline.\n")
        results = [await _run_job("pre-commit", ["pre-commit", "run", "--hook-stage", "pre-commit"], asyncio.Lock())]
    else:
        try:
            with staged_files_only(Store().directory):
                results = await _run_hooks(staged)
        except ValueError as exc:
            message = f"configuration error: {exc}"
            sys.stdout.write(message + "\n")
            results = [JobResult("configuration", (), 2, 0.0, "", message)]

    passed = all(result.returncode == 0 for result in results if result.job_id != "advisory-ruff")
    snapshot_dir: str | None = None
    if not passed:
        backup_result, snapshot_dir = await _run_backup(asyncio.Lock())
        results.append(backup_result)

    report_path = _write_report(human_ts, results)
    warnings = _advisory_warnings(results)
    for hit in warnings:
        sys.stdout.write(f"warning: {hit['file']}:{hit['line']} {hit['code']} {hit['message']}\n")

    entry: dict[str, object] = {
        "timestamp": timestamp,
        "branch": branch,
        "staged_files": staged,
        "result": "pass" if passed else "fail",
        "jobs": {result.job_id: result.returncode for result in results},
        "advisory_lint_warnings": warnings,
        "report": report_path.relative_to(REPO_ROOT).as_posix(),
    }
    if snapshot_dir is not None:
        entry["snapshot_dir"] = snapshot_dir
    _append_summary(entry)

    if not passed:
        sys.stdout.write(f"Pre-commit failed; report: {report_path.relative_to(REPO_ROOT)}\n")
        if snapshot_dir:
            sys.stdout.write(f"Working state backed up to {snapshot_dir}\n")
        return 1
    return 0


def main() -> int:
    try:
        return asyncio.run(_main_async())
    except KeyboardInterrupt as exc:
        log.error("Pre-commit wrapper terminated: %s", exc)
        return 1


if __name__ == "__main__":
    log.info("Running pre-commit wrapper in %s", REPO_ROOT)
    sys.exit(main())
