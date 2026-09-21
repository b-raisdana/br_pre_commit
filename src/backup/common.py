"""Shared utilities and constants for the backup package.

This module collects configuration readers, path helpers, content-addressed
hashing, and thin git subprocess wrappers used by both the snapshot
(__main__) and recovery (recover) modules.
"""

from __future__ import annotations

import logging
import re
import zlib
from pathlib import Path

log = logging.getLogger("backup")

# class BackupSettings(TypedDict, total=False):
#     full_backup_exclude_dir_regex: str


# def _shared_backup_defaults() -> BackupSettings:
#     """Read the [tool.br_pre_commit.backup] section from pyproject.toml."""
#     data = tomllib.loads(br_pre_commit_config.py_project_toml_file_name.read_text(encoding="utf-8"))
#     tool = data.get("tool", {})
#     if not isinstance(tool, dict):
#         return BackupSettings()
#     section = tool.get("br_pre_commit", {})
#     if not isinstance(section, dict):
#         return BackupSettings()
#     backup_section = section.get("backup")
#     if not isinstance(backup_section, dict):
#         return BackupSettings()
#     return BackupSettings(
#         full_backup_exclude_dir_regex=str(
#             backup_section.get("full_backup_exclude_dir_regex", _DEFAULT_FULL_BACKUP_EXCLUDE_DIR_REGEX)
#         )
#     )


# def _backup_settings(repo_root: Path) -> BackupSettings:
#     """Load backup settings from [tool.br_pre_commit.backup] in pyproject.toml."""
#     return _shared_backup_defaults()


def flatten_path(path: str) -> str:
    return path.replace("/", "_").replace("\\", "_")


def content_hash(content: bytes) -> str:
    """Return a short, non-cryptographic content identifier."""
    return f"{zlib.crc32(content) & 0xFFFFFFFF:08x}"[-7:]


# def decode_paths(output: bytes) -> list[str]:
#     return [path.decode("utf-8", errors="surrogateescape") for path in output.split(b"\0") if path]


def is_excluded(path: str, exclude_dir: str) -> bool:
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


def subprocess_error(return_code: int, args: tuple[str, ...], stdout: bytes, stderr: bytes) -> RuntimeError:
    return RuntimeError(
        f"git {' '.join(args)} exited {return_code}: {stderr.decode('utf-8', errors='replace').strip()}"
    )
