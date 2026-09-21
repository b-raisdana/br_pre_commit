#!/usr/bin/env python3
"""Thin subprocess-backed git helper.

Replaces the GitPython ``repo.git`` raw-command interface used by
``sync_skills`` so that ``gitpython`` is no longer a runtime dependency.
Only the operations actually needed by sync-skill-files are exposed; the
high-level ``Repo.index`` object API is deliberately not used (in gitpython
3.1.x it misreports staged deletions as additions).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from helper.paths import get_user_repo_path_from_env


class GitCommandError(Exception):
    """Raised when a git subprocess fails (mirrors git.exc.GitCommandError)."""


class InvalidGitRepositoryError(Exception):
    """Raised when a path is not inside a git repository."""


async def git_cmd(
    *args: str,
    repo_root: Path | None = None,
    return_bytes: bool = False,
) -> str | bytes:
    """Run ``git -C <repo_root> <args>`` and return stdout."""
    if repo_root is None:
        repo_root = get_user_repo_path_from_env()

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=(not return_bytes),
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace") if return_bytes else exc.stderr
        raise GitCommandError(f"git -C {repo_root} {' '.join(args)} failed: {stderr.strip()}") from exc

    return result.stdout


async def get_repo(repo_root: Path | None = None) -> Path:
    """Return the git repository root for ``path``."""
    if repo_root is None:
        repo_root = get_user_repo_path_from_env()

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "git",
                "-C",
                str(repo_root),
                "rev-parse",
                "--show-toplevel",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise InvalidGitRepositoryError(f"{repo_root} is not a git repository: {exc.stderr.strip()}") from exc

    return Path(result.stdout.strip())


async def show_index_blob(
    rel: str,
    repo_root: Path | None = None,
) -> bytes | None:
    """Return the staged blob bytes for ``rel``, or ``None`` if absent."""
    if repo_root is None:
        repo_root = get_user_repo_path_from_env()

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", str(repo_root), "show", f":{rel}"],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 128:
            return None

        raise GitCommandError(f"git -C {repo_root} show :{rel} failed: {exc.stderr.strip()}") from exc

    return result.stdout


async def stage(
    rel: str,
    repo_root: Path | None = None,
) -> None:
    """Stage ``rel`` (``git add <rel>``)."""
    if repo_root is None:
        repo_root = get_user_repo_path_from_env()

    await git_cmd("add", rel, repo_root=repo_root)


async def get_staged_files() -> list[str]:
    output = await git_cmd("diff", "--cached", "--name-only")
    return output.splitlines() if output else []


async def diff_cached_name_status(
    repo_root: Path | None = None,
) -> str:
    """Return ``git diff --cached --name-status`` output."""
    if repo_root is None:
        repo_root = get_user_repo_path_from_env()

    return await git_cmd(
        "diff",
        "--cached",
        "--name-status",
        repo_root=repo_root,
    )
