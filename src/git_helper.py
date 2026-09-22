#!/usr/bin/env python3
"""Thin subprocess-backed git helper.

Replaces the GitPython ``repo.git`` raw-command interface used by
``sync_skills`` so that ``gitpython`` is no longer a runtime dependency.
Only the operations actually needed by sync-skill-files are exposed; the
high-level ``Repo.index`` object API is deliberately not used (in gitpython
3.1.x it misreports staged deletions as additions).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitCommandError(Exception):
    """Raised when a git subprocess fails (mirrors git.exc.GitCommandError)."""


class InvalidGitRepositoryError(Exception):
    """Raised when a path is not inside a git repository."""


def _git(repo_root: Path, *args: str) -> str:
    """Run ``git -C <repo_root> <args>`` and return stripped stdout."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise GitCommandError(f"git -C {repo_root} {' '.join(args)} failed: {exc.stderr.strip()}") from exc
    return result.stdout


def get_repo(path: Path) -> Path:
    """Return the git repository root for ``path``.

    Raises :class:`InvalidGitRepositoryError` when ``path`` is not inside a
    git working tree (mirrors the error case of ``git.Repo(path)`` that the
    hook relies on).
    """
    try:
        root = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise InvalidGitRepositoryError(f"{path} is not a git repository: {exc.stderr.strip()}") from exc
    return Path(root)


def show_index_blob(repo_root: Path, rel: str) -> bytes | None:
    """Return the staged blob bytes for ``rel`` (``git show :<rel>``), or None.

    A missing staged blob (not in the index) is the expected "no such name in
    the index" case and returns ``None`` rather than raising.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "show", f":{rel}"],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 128:
            return None
        raise GitCommandError(f"git -C {repo_root} show :{rel} failed: {exc.stderr.strip()}") from exc
    return result.stdout


def stage(repo_root: Path, rel: str) -> None:
    """Stage ``rel`` (``git add <rel>``)."""
    _git(repo_root, "add", rel)


def diff_cached_name_status(repo_root: Path) -> str:
    """Return ``git diff --cached --name-status`` output."""
    return _git(repo_root, "diff", "--cached", "--name-status")
