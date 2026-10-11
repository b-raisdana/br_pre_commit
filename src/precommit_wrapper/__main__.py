"""Run the pre-commit pipeline with advisory checks and live logs.

See README.md for the module map, scheduling rules, and exit codes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import sys
from collections.abc import Awaitable
from dataclasses import dataclass

from ..helper.paths import get_br_pre_commit_package_prefix_from_env, get_user_repo_path_from_env
from .config import wrapper_config

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


def _branch_protection_result(branch: str) -> JobResult | None:
    if not re.fullmatch(wrapper_config.protected_branches_regex, branch):
        return None
    merge_in_progress = subprocess.run(
        ["git", "-C", str(get_user_repo_path_from_env()), "rev-parse", "--verify", "--quiet", "MERGE_HEAD"],
        check=False,
        capture_output=True,
    )
    if merge_in_progress.returncode == 0:
        return None
    message = f"Direct commits to protected branch '{branch}' are not allowed. Create a feature branch."
    return JobResult("branch-protection", (), 1, 0.0, "", message)


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
            cwd=get_user_repo_path_from_env(),
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
            return_code = await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
        except TimeoutError:
            await _terminate_process_group(proc)
            stderr_parts.append(f"timed out after {timeout_seconds:g}s\n")
            return_code = 124
        finally:
            await asyncio.gather(stdout_task, stderr_task)
    except asyncio.CancelledError:
        await _terminate_process_group(proc)
        await asyncio.gather(stdout_task, stderr_task)
        raise
    duration = loop.time() - started
    async with terminal_lock:
        sys.stdout.write(f"[{job_id}] finished ({return_code}) in {duration:.2f}s\n")
        sys.stdout.flush()
    return JobResult(job_id, tuple(command), return_code, duration, "".join(stdout_parts), "".join(stderr_parts))


def _pipeline_command(staged: list[str]) -> list[str]:
    return ["pre-commit", "run", "--hook-stage", "pre-commit", "--color", "never", "--files", *staged]


async def _terminate_process_group(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return

    if os.name == "nt":
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except TimeoutError:
            proc.kill()
            await proc.wait()
        return

    try:
        os.killpg(proc.pid, signal.SIGTERM)
        await asyncio.wait_for(proc.wait(), timeout=3)
    except ProcessLookupError:
        return
    except TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        await proc.wait()


def _advisory_jobs(py_files: list[str], terminal_lock: asyncio.Lock, timeout: float) -> list[Awaitable[JobResult]]:
    if not py_files:
        return []
    return [
        _run_job(
            "advisory-ruff",
            ["ruff", "check", "--select", ADVISORY_RUFF_RULES, "--output-format=json", *py_files],
            terminal_lock,
            stream_output=False,
            timeout_seconds=timeout,
        ),
        _run_job(
            "advisory-radon",
            ["radon", "mi", "--show", "--min", "B", "--max", "C", *py_files],
            terminal_lock,
            stream_output=False,
            timeout_seconds=timeout,
        ),
    ]


async def _run_hooks(staged: list[str]) -> list[JobResult]:
    timeout = wrapper_config.job_timeout_seconds
    terminal_lock = asyncio.Lock()
    py_files = [
        f
        for f in staged
        if (f.startswith("src/") and f.endswith(".py") and (get_user_repo_path_from_env() / f).exists())
    ]
    jobs = [
        _run_job(
            "pre-commit",
            _pipeline_command(staged),
            terminal_lock,
            timeout_seconds=timeout,
        )
    ]
    jobs.extend(_advisory_jobs(py_files, terminal_lock, timeout))
    return await asyncio.gather(*jobs)


async def _run_backup(terminal_lock: asyncio.Lock) -> tuple[JobResult, str | None]:
    result = await _run_job(
        "backup",
        [
            sys.executable,
            "-m",
            f"{get_br_pre_commit_package_prefix_from_env()}.backup",
            "--repo",
            str(get_user_repo_path_from_env()),
        ],
        terminal_lock,
        timeout_seconds=wrapper_config.job_timeout_seconds,
    )
    try:
        snapshot_dir = json.loads(result.stdout.splitlines()[-1])["snapshot_dir"] if result.returncode == 0 else None
    except (IndexError, KeyError, json.JSONDecodeError):
        snapshot_dir = None
    return result, snapshot_dir


from .report import (  # noqa: E402, F401
    main,
)

if __name__ == "__main__":
    sys.exit(main())
