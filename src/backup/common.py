"""Shared utilities and constants for the backup package.

This module collects configuration readers, path helpers, content-addressed
hashing, and thin git subprocess wrappers used by both the snapshot
(__main__) and recovery (recover) modules.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import tomllib
import zlib
from pathlib import Path
from typing import TypedDict

log = logging.getLogger("backup")

STAGED_PREFIX = "staged"
UNSTAGED_PREFIX = "unstaged"
UNTRACKED_PREFIX = "untracked"
FULL_BACKUP_DIR = "full_backup"

_DEFAULT_FULL_BACKUP_EXCLUDE_DIR_REGEX = r"^(data|logs|\.[^/]+)$"

PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"


class BackupSettings(TypedDict, total=False):
    full_backup_exclude_dir_regex: str


def _shared_backup_defaults() -> BackupSettings:
    """Read the [tool.br_pre_commit.backup] section from pyproject.toml."""
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    tool = data.get("tool", {})
    if not isinstance(tool, dict):
        return BackupSettings()
    section = tool.get("br_pre_commit", {})
    if not isinstance(section, dict):
        return BackupSettings()
    backup_section = section.get("backup")
    if not isinstance(backup_section, dict):
        return BackupSettings()
    return BackupSettings(
        full_backup_exclude_dir_regex=str(
            backup_section.get("full_backup_exclude_dir_regex", _DEFAULT_FULL_BACKUP_EXCLUDE_DIR_REGEX)
        )
    )


def _backup_settings(repo_root: Path) -> BackupSettings:
    """Load backup settings from [tool.br_pre_commit.backup] in pyproject.toml."""
    return _shared_backup_defaults()


def _flatten_path(path: str) -> str:
    return path.replace("/", "_").replace("\\", "_")


def _content_hash(content: bytes) -> str:
    """Return a short, non-cryptographic content identifier."""
    return f"{zlib.crc32(content) & 0xFFFFFFFF:08x}"[-7:]


def _decode_paths(output: bytes) -> list[str]:
    return [path.decode("utf-8", errors="surrogateescape") for path in output.split(b"\0") if path]


def _is_excluded(path: str, exclude_dir: str) -> bool:
    """Return True when ``path`` is under the configured exclude directory.

    ``exclude_dir`` may be either a literal directory name (matched against any
    path part) or a regex anchored to match a single path part.
    """
    if not exclude_dir:
        return False
    parts = Path(path).parts
    try:
        pattern = re.compile(exclude_dir)
    except re.error:
        # Literal directory name - match against any path part.
        return exclude_dir in parts
    # Regex - each path part is matched in full.
    return any(pattern.fullmatch(part) for part in parts)


def _get_full_backup_dir(repo_root: Path) -> Path:
    return repo_root / "logs" / "pre-commit" / FULL_BACKUP_DIR


def subprocess_error(returncode: int, args: tuple[str, ...], stdout: bytes, stderr: bytes) -> RuntimeError:
    return RuntimeError(f"git {' '.join(args)} exited {returncode}: {stderr.decode('utf-8', errors='replace').strip()}")


async def _git(repo_root: Path, *args: str) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=repo_root, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        log.error("git %s failed: %s", " ".join(args), stderr.decode("utf-8", errors="replace").strip())
        raise subprocess_error(proc.returncode, args, stdout, stderr)
    return stdout


def _run_git(repo_root: Path, *args: str) -> str:
    """Run a synchronous git command, raising CalledProcessError on failure."""
    result = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True, check=False)
    if result.returncode:
        message = result.stderr.strip()
        raise subprocess.CalledProcessError(result.returncode, ["git", *args], output=result.stdout, stderr=message)
    return result.stdout.strip()
