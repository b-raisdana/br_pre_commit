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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402

from backup.models import Manifest  # noqa: E402

from .common import (  # noqa: E402
    _DEFAULT_FULL_BACKUP_EXCLUDE_DIR_REGEX,
    STAGED_PREFIX,
    UNSTAGED_PREFIX,
    UNTRACKED_PREFIX,
    _backup_settings,
    _content_hash,
    _decode_paths,
    _flatten_path,
    _get_full_backup_dir,
    _git,
    _is_excluded,
)

logging.basicConfig(level=logging.DEBUG, format="%(message)s")
log = logging.getLogger("backup")


def _write_manifest(path: Path, manifest: Manifest) -> None:
    path.write_text(json.dumps(asdict(manifest), indent=2) + "\n", encoding="utf-8")


def _write_patch(snapshot_dir: Path, prefix: str, path: str, patch: bytes) -> dict[str, str]:
    entry = {"original_path": path}
    try:
        content = patch + b"\n"
        source_path = Path(path)
        ext = source_path.suffix.lstrip(".") or "bin"
        stored_path = Path(prefix) / source_path.with_name(f"{source_path.stem}.{ext}.{_content_hash(content)}.patch")
        destination = snapshot_dir / stored_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        entry.update(type="patch", stored_path=stored_path.as_posix())
    except Exception as exc:
        log.exception("Failed to backup %s %s: %s", prefix, path, exc)
        entry.update(type="failed", error=str(exc))
    return entry


def _is_text_file(path: Path) -> bool:
    """Check if a file is a text file (UTF-8 decodable)."""
    try:
        path.read_text(encoding="utf-8")
        return True
    except UnicodeDecodeError:
        return False
    except Exception:
        return False


def _copy_full_file(
    full_backup_dir: Path, repo_root: Path, path: str, *, text_only: bool = False
) -> dict[str, str] | None:
    source = repo_root / path
    if not source.is_file():
        return None
    if text_only and not _is_text_file(source):
        return None
    try:
        content = source.read_bytes()
    except Exception as exc:
        log.exception("Failed to read %s for full backup: %s", path, exc)
        return {"original_path": path, "type": "failed", "error": str(exc)}
    try:
        path_obj = Path(path)
        stem = path_obj.stem
        ext = path_obj.suffix.lstrip(".") or "bin"
        hash_suffix = _content_hash(content)
        stored_name = f"{stem}.{hash_suffix}.{ext}"
        stored_path = path_obj.with_name(stored_name)
        destination = full_backup_dir / stored_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return {"original_path": path, "type": "full", "stored_path": stored_path.as_posix()}
    except Exception as exc:
        log.exception("Failed to backup full file %s: %s", path, exc)
        return {"original_path": path, "type": "failed", "error": str(exc)}


def _snapshot_size(snapshot_dir: Path) -> int:
    return sum(path.stat().st_size for path in snapshot_dir.rglob("*") if path.is_file())


async def _backup_diff(snapshot_dir: Path, repo_root: Path, prefix: str, path: str) -> dict[str, str]:
    cached = ("--cached",) if prefix == STAGED_PREFIX else ()
    patch = await _git(repo_root, "diff", "--binary", *cached, "--", path)
    return await asyncio.to_thread(_write_patch, snapshot_dir, prefix, path, patch)


def _copy_untracked(snapshot_dir: Path, repo_root: Path, path: str) -> dict[str, str] | None:
    source = repo_root / path
    if not source.is_file():
        return None
    try:
        source.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None

    destination = snapshot_dir / UNTRACKED_PREFIX / path
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return {"original_path": path, "stored_path": destination.relative_to(snapshot_dir).as_posix()}
    except Exception as exc:
        log.exception("Failed to backup untracked %s: %s", path, exc)
        return {"original_path": path, "stored_path": "None", "error": str(exc)}


async def _backup_many_diffs(
    snapshot_dir: Path, repo_root: Path, prefix: str, paths: list[str]
) -> list[dict[str, str]]:
    entries = await asyncio.gather(*(_backup_diff(snapshot_dir, repo_root, prefix, path) for path in paths))
    return sorted(entries, key=lambda entry: entry["original_path"])


async def _backup_untracked(snapshot_dir: Path, repo_root: Path, paths: list[str]) -> list[dict[str, str]]:
    entries = await asyncio.gather(
        *(asyncio.to_thread(_copy_untracked, snapshot_dir, repo_root, path) for path in paths)
    )
    return sorted((entry for entry in entries if entry is not None), key=lambda entry: entry["original_path"])


async def _get_all_tracked_files(repo_root: Path) -> list[str]:
    """Get all files tracked by git in the repository."""
    output = await _git(repo_root, "ls-files", "-z")
    return _decode_paths(output)


async def _backup_all_tracked_files(full_backup_dir: Path, repo_root: Path, exclude_regex: str) -> list[dict[str, str]]:
    """Copy all tracked text files (except those matching exclude_regex) to full backup store."""
    all_tracked = await _get_all_tracked_files(repo_root)
    filtered = [p for p in all_tracked if not _is_excluded(p, exclude_regex)]
    entries = await asyncio.gather(
        *(asyncio.to_thread(_copy_full_file, full_backup_dir, repo_root, path, text_only=True) for path in filtered)
    )
    return sorted((entry for entry in entries if entry is not None), key=lambda entry: entry["original_path"])


def _split_by_exclude(paths: list[str], exclude_regex: str) -> tuple[list[str], list[str]]:
    keep: list[str] = []
    full: list[str] = []
    for path in paths:
        (full if _is_excluded(path, exclude_regex) else keep).append(path)
    return keep, full


async def _gather_git_info(repo_root: Path) -> tuple[str, str, list[str], list[str], list[str]]:
    branch_raw, commit_raw, staged_raw, unstaged_raw, untracked_raw = await asyncio.gather(
        _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
        _git(repo_root, "rev-parse", "HEAD"),
        _git(repo_root, "diff", "--cached", "--name-only", "-z"),
        _git(repo_root, "diff", "--name-only", "-z"),
        _git(repo_root, "ls-files", "--others", "--exclude-standard", "-z"),
    )
    branch = branch_raw.decode().strip()
    commit_hash = commit_raw.decode().strip()
    return branch, commit_hash, _decode_paths(staged_raw), _decode_paths(unstaged_raw), _decode_paths(untracked_raw)


async def _build_full_backups(
    full_backup_dir: Path,
    repo_root: Path,
    exclude_regex: str,
    staged_full: list[str],
    unstaged_full: list[str],
    untracked_full: list[str],
) -> list[dict[str, str]]:
    full_entries = await asyncio.gather(
        *(
            asyncio.to_thread(_copy_full_file, full_backup_dir, repo_root, path, text_only=True)
            for path in staged_full + unstaged_full + untracked_full
        )
    )
    full_backups = sorted(
        (entry for entry in full_entries if entry is not None),
        key=lambda entry: entry["original_path"],
    )
    all_tracked_backups = await _backup_all_tracked_files(full_backup_dir, repo_root, exclude_regex)
    existing_paths = {entry["original_path"] for entry in full_backups}
    for entry in all_tracked_backups:
        if entry["original_path"] not in existing_paths:
            full_backups.append(entry)
    full_backups.sort(key=lambda entry: entry["original_path"])
    return full_backups


async def take_snapshot_async(repo_root: Path) -> Manifest:
    log.debug("Taking snapshot %s...", repo_root)
    branch, commit_hash, staged_paths, unstaged_paths, untracked_paths = await _gather_git_info(repo_root)
    snapshot_dir = get_snapshot_dir(branch, commit_hash, repo_root)

    settings = _backup_settings(repo_root)
    exclude_regex = settings.get("full_backup_exclude_dir_regex", _DEFAULT_FULL_BACKUP_EXCLUDE_DIR_REGEX)

    staged_keep, staged_full = _split_by_exclude(staged_paths, exclude_regex)
    unstaged_keep, unstaged_full = _split_by_exclude(unstaged_paths, exclude_regex)
    untracked_keep, untracked_full = _split_by_exclude(untracked_paths, exclude_regex)

    full_backup_dir = _get_full_backup_dir(repo_root)
    full_backups = await _build_full_backups(
        full_backup_dir, repo_root, exclude_regex, staged_full, unstaged_full, untracked_full
    )

    staged, unstaged, untracked = await asyncio.gather(
        _backup_many_diffs(snapshot_dir, repo_root, STAGED_PREFIX, staged_keep),
        _backup_many_diffs(snapshot_dir, repo_root, UNSTAGED_PREFIX, unstaged_keep),
        _backup_untracked(snapshot_dir, repo_root, untracked_keep),
    )
    manifest = Manifest(
        branch=branch,
        commit_hash=commit_hash,
        timestamp=datetime.now().strftime("%Y%m%dT%H%M%S"),
        snapshot_dir=snapshot_dir.relative_to(repo_root).as_posix(),
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


def take_snapshot(repo_root: Path) -> Manifest:
    return asyncio.run(take_snapshot_async(repo_root))


def get_snapshot_dir(branch: str, commit_hash: str, repo_root: Path) -> Path:
    snapshot_dir = repo_root / "logs" / "pre-commit" / "backup-patches" / f"{_flatten_path(branch)}.{commit_hash[:7]}"
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log.exception("Failed to create snapshot directory %s: %s", snapshot_dir, exc)
        raise
    return snapshot_dir


async def _main_async(repo_root: Path, *, print_manifest_json: bool) -> int:
    try:
        manifest = await take_snapshot_async(repo_root)
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
