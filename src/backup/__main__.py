#!/usr/bin/env python3
"""Create a read-only working-state snapshot with concurrent Git and file I/O."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import cast

from ..helper.git import git_cmd
from ..helper.paths import get_backup_manifest_dir, get_full_backup_dir, get_log_dir
from .common import flatten_path, is_excluded
from .config import backup_config
from .helpers import (
    _attempt_timestamp,
    _copy_full_file,
    _snapshot_size,
    _write_attempt_manifest,
    _write_manifest,
    _write_patch,
)
from .models import Manifest


class _BackupFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now().strftime("%m-%dT%H-%M-%S")
        msg = record.getMessage()
        return f"[{ts}:backup] {msg}"


logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger("backup")
for h in log.handlers:
    h.setFormatter(_BackupFormatter())
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(_BackupFormatter())
    log.addHandler(h)
log.propagate = False


async def _backup_diff(snapshot_dir: Path, user_repo_root: Path, prefix: str, path: str) -> dict[str, str]:
    cached = ("--cached",) if prefix == backup_config.staged_prefix else ()
    patch = await git_cmd("diff", "--binary", *cached, "--", path, git_repo_root=user_repo_root, return_bytes=True)
    assert isinstance(patch, bytes)
    return await asyncio.to_thread(_write_patch, snapshot_dir, prefix, path, patch)


def _copy_untracked(snapshot_dir: Path, user_repo_root: Path, path: str) -> dict[str, str] | None:
    source = user_repo_root / path
    if not source.is_file():
        return None
    try:
        source.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None

    destination = snapshot_dir / backup_config.untracked_prefix / path
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return {"original_path": path, "stored_path": destination.relative_to(snapshot_dir).as_posix()}
    except Exception as exc:
        log.exception("Failed to backup untracked %s: %s", path, exc)
        return {"original_path": path, "stored_path": "None", "error": str(exc)}


async def _backup_many_diffs(
    snapshot_dir: Path, user_repo_root: Path, prefix: str, paths: list[str]
) -> list[dict[str, str]]:
    entries = await asyncio.gather(*(_backup_diff(snapshot_dir, user_repo_root, prefix, path) for path in paths))
    return sorted(entries, key=lambda entry: entry["original_path"])


async def _backup_untracked(snapshot_dir: Path, user_repo_root: Path, paths: list[str]) -> list[dict[str, str]]:
    entries = await asyncio.gather(
        *(asyncio.to_thread(_copy_untracked, snapshot_dir, user_repo_root, path) for path in paths)
    )
    return sorted((entry for entry in entries if entry is not None), key=lambda entry: entry["original_path"])


async def _get_all_tracked_files(user_repo_root: Path) -> list[str]:
    """Get all files tracked by git in the repository."""
    output = await git_cmd("ls-files", git_repo_root=user_repo_root)
    return cast(list[str], output.splitlines())


async def _backup_all_tracked_files(
    full_backup_dir: Path,
    user_repo_root: Path,
    exclude_regex: str,
) -> list[dict[str, str]]:
    """Copy all tracked text files (except those matching exclude_regex) to full backup store."""
    all_tracked = await _get_all_tracked_files(user_repo_root)
    filtered = [p for p in all_tracked if not is_excluded(p, exclude_regex)]
    entries = await asyncio.gather(
        *(
            asyncio.to_thread(_copy_full_file, full_backup_dir, user_repo_root, path, text_only=True)
            for path in filtered
        )
    )
    return sorted((entry for entry in entries if entry is not None), key=lambda entry: entry["original_path"])


def _split_by_exclude(paths: list[str], exclude_regex: str) -> tuple[list[str], list[str]]:
    keep: list[str] = []
    full: list[str] = []
    for path in paths:
        (full if is_excluded(path, exclude_regex) else keep).append(path)
    return keep, full


async def _gather_git_info(user_repo_root: Path) -> tuple[str, str, list[str], list[str], list[str]]:
    branch_raw, commit_raw, staged_raw, unstaged_raw, untracked_raw = await asyncio.gather(
        git_cmd("rev-parse", "--abbrev-ref", "HEAD", git_repo_root=user_repo_root),
        git_cmd("rev-parse", "HEAD", git_repo_root=user_repo_root),
        git_cmd("diff", "--cached", "--name-only", git_repo_root=user_repo_root),
        git_cmd("diff", "--name-only", git_repo_root=user_repo_root),
        git_cmd("ls-files", "--others", "--exclude-standard", git_repo_root=user_repo_root),
    )
    branch = cast(str, branch_raw.strip())
    commit_hash = cast(str, commit_raw.strip())
    staged = cast(list[str], staged_raw.splitlines())
    unstaged = cast(list[str], unstaged_raw.splitlines())
    untracked = cast(list[str], untracked_raw.splitlines())
    return branch, commit_hash, staged, unstaged, untracked


async def _build_full_backups(
    full_backup_dir: Path,
    user_repo_root: Path,
    exclude_regex: str,
    staged_full: list[str],
    unstaged_full: list[str],
    untracked_full: list[str],
) -> list[dict[str, str]]:
    full_entries = await asyncio.gather(
        *(
            asyncio.to_thread(_copy_full_file, full_backup_dir, user_repo_root, path, text_only=True)
            for path in staged_full + unstaged_full + untracked_full
        )
    )
    full_backups = sorted(
        (entry for entry in full_entries if entry is not None),
        key=lambda entry: entry["original_path"],
    )
    all_tracked_backups = await _backup_all_tracked_files(full_backup_dir, user_repo_root, exclude_regex)
    existing_paths = {entry["original_path"] for entry in full_backups}
    for entry in all_tracked_backups:
        if entry["original_path"] not in existing_paths:
            full_backups.append(entry)
    full_backups.sort(key=lambda entry: entry["original_path"])
    return full_backups


async def take_snapshot_async(user_repo_root: Path) -> Manifest:
    log.debug("Taking snapshot %s...", user_repo_root)
    attempt_ts = _attempt_timestamp()
    branch, commit_hash, staged_paths, unstaged_paths, untracked_paths = await _gather_git_info(user_repo_root)
    snapshot_dir = get_snapshot_dir(branch, commit_hash, user_repo_root)

    exclude_regex = backup_config.full_backup_exclude_dir_regex

    staged_keep, staged_full = _split_by_exclude(staged_paths, exclude_regex)
    unstaged_keep, unstaged_full = _split_by_exclude(unstaged_paths, exclude_regex)
    untracked_keep, untracked_full = _split_by_exclude(untracked_paths, exclude_regex)

    full_backup_dir = get_full_backup_dir()
    full_backups, (staged, unstaged, untracked) = await asyncio.gather(
        _build_full_backups(full_backup_dir, user_repo_root, exclude_regex, staged_full, unstaged_full, untracked_full),
        asyncio.gather(
            _backup_many_diffs(snapshot_dir, user_repo_root, backup_config.staged_prefix, staged_keep),
            _backup_many_diffs(snapshot_dir, user_repo_root, backup_config.unstaged_prefix, unstaged_keep),
            _backup_untracked(snapshot_dir, user_repo_root, untracked_keep),
        ),
    )
    manifest = Manifest(
        branch=branch,
        commit_hash=commit_hash,
        timestamp=attempt_ts.replace("-", "").replace(":", ""),
        snapshot_dir=snapshot_dir.relative_to(user_repo_root).as_posix(),
        staged=staged,
        unstaged=unstaged,
        untracked=untracked,
        full_backups=full_backups,
    )
    try:
        await asyncio.to_thread(_write_manifest, snapshot_dir / "manifest.json", manifest)
    except Exception as exc:
        log.exception("Failed to write manifest: %s", exc)
        raise

    manifest.attempt_timestamp = attempt_ts
    try:
        await asyncio.to_thread(
            _write_attempt_manifest,
            get_backup_manifest_dir(),
            attempt_ts,
            snapshot_dir,
            full_backup_dir,
            manifest,
        )
    except Exception as exc:
        log.exception("Failed to write attempt manifest: %s", exc)
        raise

    total_size = await asyncio.to_thread(_snapshot_size, snapshot_dir)
    log.info(
        "Snapshot saved to %s | %d staged, %d unstaged, %d untracked, %d full | %.1f KB",
        snapshot_dir,
        sum(entry.get("type") == "patch" for entry in staged),
        sum(entry.get("type") == "patch" for entry in unstaged),
        sum("error" not in entry for entry in untracked),
        len(full_backups),
        total_size / 1024.0,
    )
    return manifest


def take_snapshot(user_repo_root: Path) -> Manifest:
    return asyncio.run(take_snapshot_async(user_repo_root))


def get_snapshot_dir(branch: str, commit_hash: str, user_repo_root: Path) -> Path:
    snapshot_dir = get_log_dir() / "backup-patches" / f"{flatten_path(branch)}.{commit_hash[:7]}"
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log.exception("Failed to create snapshot directory %s: %s", snapshot_dir, exc)
        raise
    assert isinstance(snapshot_dir, Path)
    return snapshot_dir


async def _main_async(user_repo_root: Path, *, print_manifest_json: bool) -> int:
    try:
        manifest = await take_snapshot_async(user_repo_root)
    except Exception as exc:
        log.exception("Backup failed: %s", exc)
        return 1
    if print_manifest_json:
        print(json.dumps(asdict(manifest)))
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Backup working state to disk (read-only)")
    parser.add_argument("--repo", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--print-manifest-json", default=False, action="store_true")
    args = parser.parse_args()
    return asyncio.run(_main_async(args.repo.resolve(), print_manifest_json=args.print_manifest_json))


if __name__ == "__main__":
    result = main()
    log.debug("Backup script exited with code %d", result)
    sys.exit(result)
