"""UTF-8-safe subprocess helpers used by ratchet analyzers."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from ..helper.paths import get_user_repo_path_from_env, git_subprocess_env


def run(*args: str, cwd: Path | None = None) -> str:
    """Run a command and return stdout, decoding output consistently on Windows."""
    result = subprocess.run(
        args,
        cwd=cwd or get_user_repo_path_from_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=git_subprocess_env(),
    )
    return result.stdout


async def async_run(*args: str, cwd: Path | None = None) -> str:
    return await asyncio.to_thread(run, *args, cwd=cwd)


def output_run(*args: str, cwd: Path | None = None) -> str:
    """Run a command and return both output streams as UTF-8 text."""
    result = subprocess.run(
        args,
        cwd=cwd or get_user_repo_path_from_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=git_subprocess_env(),
    )
    return result.stdout + result.stderr


async def async_output_run(*args: str, cwd: Path | None = None) -> str:
    return await asyncio.to_thread(output_run, *args, cwd=cwd)
