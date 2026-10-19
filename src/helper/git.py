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
from typing import Literal, cast, overload

from .paths import get_user_repo_path_from_env, git_subprocess_env


class GitCommandError(Exception):
    """Raised when a git subprocess fails (mirrors git.exc.GitCommandError)."""


class InvalidGitRepositoryError(Exception):
    """Raised when a path is not inside a git repository."""


@overload
def run_git(
    *args: str,
    git_repo_root: Path | None = None,
    text: Literal[True] = True,
    scrub_environment: bool = True,
    inherit_index: bool = True,
) -> subprocess.CompletedProcess[str]: ...


@overload
def run_git(
    *args: str,
    git_repo_root: Path | None = None,
    text: Literal[False],
    scrub_environment: bool = True,
    inherit_index: bool = True,
) -> subprocess.CompletedProcess[bytes]: ...


def run_git(
    *args: str,
    git_repo_root: Path | None = None,
    text: bool = True,
    scrub_environment: bool = True,
    inherit_index: bool = True,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    """Run Git with explicit repository, output, and hook-environment policies."""
    if git_repo_root is None:
        git_repo_root = get_user_repo_path_from_env()
    command = ["git", "-C", str(git_repo_root), *args]
    env = git_subprocess_env(inherit_index=inherit_index) if scrub_environment else None
    if text:
        return subprocess.run(command, check=True, capture_output=True, text=True, env=env)
    return subprocess.run(command, check=True, capture_output=True, text=False, env=env)


def git_cmd_sync(git_repo_root: Path, *args: str) -> str:
    """Run a synchronous Git command without altering the caller's environment."""
    result = run_git(*args, git_repo_root=git_repo_root, scrub_environment=False)
    return result.stdout


def get_repo_sync(path: Path) -> Path:
    """Return the repository root for ``path`` or raise the shared repository error."""
    try:
        output = git_cmd_sync(path, "rev-parse", "--show-toplevel")
    except subprocess.CalledProcessError as exc:
        raise InvalidGitRepositoryError(f"{path} is not a git repository: {exc.stderr.strip()}") from exc
    return Path(output.strip())


def show_index_blob_sync(git_repo_root: Path, rel: str) -> bytes | None:
    """Return staged blob bytes without changing the caller's Git environment."""
    try:
        result = run_git("show", f":{rel}", git_repo_root=git_repo_root, text=False, scrub_environment=False)
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 128:
            return None
        detail = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
        raise GitCommandError(f"git -C {git_repo_root} show :{rel} failed: {detail.strip()}") from exc
    return result.stdout


def stage_sync(git_repo_root: Path, rel: str) -> None:
    """Stage ``rel`` through the synchronous compatibility API."""
    git_cmd_sync(git_repo_root, "add", rel)


def diff_cached_name_status_sync(git_repo_root: Path) -> str:
    """Return staged name-status output through the synchronous compatibility API."""
    return git_cmd_sync(git_repo_root, "diff", "--cached", "--name-status")


async def git_cmd(
    *args: str,
    git_repo_root: Path | None = None,
    return_bytes: bool = False,
) -> str | bytes:
    """Run ``git -C <git_repo_root> <args>`` and return stdout."""
    result: subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]
    try:
        if return_bytes:
            result = await asyncio.to_thread(lambda: run_git(*args, git_repo_root=git_repo_root, text=False))
        else:
            result = await asyncio.to_thread(lambda: run_git(*args, git_repo_root=git_repo_root, text=True))
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace") if return_bytes else exc.stderr
        repo = git_repo_root or get_user_repo_path_from_env()
        raise GitCommandError(f"git -C {repo} {' '.join(args)} failed: {stderr.strip()}") from exc

    return result.stdout


async def get_repo(git_repo_root: Path | None = None) -> Path:
    """Return the git repository root for ``path``."""
    if git_repo_root is None:
        git_repo_root = get_user_repo_path_from_env()
    try:
        result = await asyncio.to_thread(lambda: run_git("rev-parse", "--show-toplevel", git_repo_root=git_repo_root))
    except subprocess.CalledProcessError as exc:
        raise InvalidGitRepositoryError(f"{git_repo_root} is not a git repository: {exc.stderr.strip()}") from exc

    return Path(result.stdout.strip())


async def show_index_blob(
    rel: str,
    git_repo_root: Path | None = None,
) -> bytes | None:
    """Return the staged blob bytes for ``rel``, or ``None`` if absent."""
    try:
        result = await asyncio.to_thread(lambda: run_git("show", f":{rel}", git_repo_root=git_repo_root, text=False))
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 128:
            return None

        repo = git_repo_root or get_user_repo_path_from_env()
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
        raise GitCommandError(f"git -C {repo} show :{rel} failed: {stderr.strip()}") from exc

    return result.stdout


async def stage(
    rel: str,
    git_repo_root: Path | None = None,
) -> None:
    """Stage ``rel`` (``git add <rel>``)."""
    if git_repo_root is None:
        git_repo_root = get_user_repo_path_from_env()

    await git_cmd("add", rel, git_repo_root=git_repo_root)


async def get_staged_files() -> list[str]:
    output = await git_cmd("diff", "--cached", "--name-only")
    return cast(list[str], output.splitlines()) if output else []


async def diff_cached_name_status(
    git_repo_root: Path | None = None,
) -> str:
    """Return ``git diff --cached --name-status`` output."""
    if git_repo_root is None:
        git_repo_root = get_user_repo_path_from_env()

    return cast(
        str,
        await git_cmd(
            "diff",
            "--cached",
            "--name-status",
            git_repo_root=git_repo_root,
        ),
    )
