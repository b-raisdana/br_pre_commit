#!/usr/bin/env python3
"""recover.py — restore working state from a backup snapshot.

This is the only script allowed to touch shared git state. Its mutating
steps are wrapped in an advisory file lock (.git/recover.lock) so that
concurrent sensitive operations can detect each other. The lock is
advisory, not mandatory: it only protects against callers that also
check for it.
"""

from __future__ import annotations

import fcntl
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import TextIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402

from backup.models import Manifest  # noqa: E402

from .common import (  # noqa: E402
    _get_full_backup_dir,
    _run_git,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("recover")


def _load_manifest(snapshot_dir: Path) -> Manifest:
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in {snapshot_dir}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return Manifest(**data)


def _acquire_lock(repo_root: Path, timeout: float = 5.0) -> TextIO:
    lock_path = repo_root / ".git" / "recover.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = lock_path.open("w")
    deadline = time.time() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.time() >= deadline:
                raise TimeoutError(
                    f"Could not acquire recover.lock within {timeout:.1f}s — "
                    "another recovery or sensitive git operation is in progress."
                ) from None
            time.sleep(0.1)


def _release_lock(fd: TextIO) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()
    except Exception:
        pass


def _git_error(exc: subprocess.CalledProcessError, category: str, path: str) -> str:
    """Format a git failure for the failures list and log."""
    detail = (exc.stderr or exc.stdout).strip()
    return f"{category} {path}: {detail}"


def _recover_patches(
    repo_root: Path,
    snapshot_dir: Path,
    entries: list[dict[str, str]],
    category: str,
    cached: bool,
    dry_run: bool,
) -> list[str]:
    failures: list[str] = []
    for entry in entries:
        if entry.get("type") != "patch":
            continue
        src = snapshot_dir / entry["stored_path"]
        if not src.exists():
            failures.append(f"{category} {entry['original_path']}: missing {src}")
            continue
        if dry_run:
            log.info("[dry-run] would restore %s %s", category, entry["original_path"])
            continue
        try:
            if cached:
                _run_git(repo_root, "reset", "HEAD", "--", entry["original_path"])
                _run_git(repo_root, "apply", "--cached", str(src))
            else:
                _run_git(repo_root, "apply", str(src))
            log.info("Restored %s %s", category, entry["original_path"])
        except subprocess.CalledProcessError as exc:
            msg = _git_error(exc, category, entry["original_path"])
            failures.append(msg)
            log.error(
                "Failed to restore %s %s: %s", category, entry["original_path"], (exc.stderr or exc.stdout).strip()
            )
    return failures


def _recover_untracked(
    repo_root: Path,
    snapshot_dir: Path,
    entries: list[dict[str, str]],
    dry_run: bool,
) -> list[str]:
    failures: list[str] = []
    for entry in entries:
        stored_path = entry.get("stored_path", "")
        if not stored_path or stored_path == "None":
            continue
        src = snapshot_dir / stored_path
        if not src.exists():
            failures.append(f"untracked {entry['original_path']}: missing {src}")
            continue
        if dry_run:
            log.info("[dry-run] would restore untracked %s", entry["original_path"])
            continue
        try:
            dest = repo_root / entry["original_path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
            log.info("Restored untracked %s", entry["original_path"])
        except Exception as exc:
            failures.append(f"untracked {entry['original_path']}: {exc}")
            log.error("Failed to restore untracked %s: %s", entry["original_path"], exc)
    return failures


def _recover_full(
    repo_root: Path,
    full_backup_dir: Path,
    entries: list[dict[str, str]],
    dry_run: bool,
) -> list[str]:
    """Restore excluded-path files from the persistent content-addressed full-backup store."""
    failures: list[str] = []
    for entry in entries:
        stored_path = entry.get("stored_path", "")
        if not stored_path or entry.get("type") != "full":
            continue
        src = full_backup_dir / stored_path
        if not src.exists():
            failures.append(f"full {entry['original_path']}: missing {src}")
            continue
        if dry_run:
            log.info("[dry-run] would restore full %s", entry["original_path"])
            continue
        try:
            dest = repo_root / entry["original_path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
            log.info("Restored full %s", entry["original_path"])
        except Exception as exc:
            failures.append(f"full {entry['original_path']}: {exc}")
            log.error("Failed to restore full %s: %s", entry["original_path"], exc)
    return failures


def _checkout_commit(repo_root: Path, manifest: Manifest, dry_run: bool) -> None:
    if dry_run:
        log.info("[dry-run] would checkout commit %s", manifest.commit_hash)
        return
    _run_git(repo_root, "checkout", manifest.commit_hash)
    log.info("Checked out commit %s", manifest.commit_hash)


def _recover_category(
    repo_root: Path,
    snapshot_dir: Path,
    manifest: Manifest,
    category: str,
    dry_run: bool,
) -> list[str]:
    if category == "staged":
        return _recover_patches(repo_root, snapshot_dir, manifest.staged, category, True, dry_run)
    if category == "unstaged":
        return _recover_patches(repo_root, snapshot_dir, manifest.unstaged, category, False, dry_run)
    if category == "untracked":
        return _recover_untracked(repo_root, snapshot_dir, manifest.untracked, dry_run)
    if category == "full":
        return _recover_full(repo_root, _get_full_backup_dir(repo_root), manifest.full_backups, dry_run)
    return [f"unknown recovery category: {category}"]


def recover(
    snapshot_dir: Path,
    repo_root: Path,
    to_commit: bool = False,
    only: str | None = None,
    dry_run: bool = False,
) -> list[str]:
    manifest = _load_manifest(snapshot_dir)
    repo_root = repo_root.resolve()
    snapshot_dir = snapshot_dir.resolve()

    if dry_run:
        log.info("Dry-run mode — no changes will be made.")

    lock_fd = None
    failures = []
    try:
        if not dry_run:
            lock_fd = _acquire_lock(repo_root)

        if to_commit:
            _checkout_commit(repo_root, manifest, dry_run)

        categories = ["staged", "unstaged", "untracked"] if only is None else [only]
        for category in categories:
            failures.extend(_recover_category(repo_root, snapshot_dir, manifest, category, dry_run))
    finally:
        if lock_fd is not None:
            _release_lock(lock_fd)

    return failures


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Recover working state from a backup snapshot")
    parser.add_argument("--snapshot", type=Path, required=True, help="Path to snapshot directory")
    parser.add_argument("--to-commit", action="store_true", help="Checkout the snapshot's commit before recovery")
    parser.add_argument("--only", choices=["staged", "unstaged", "untracked", "full"], help="Restore only one category")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without touching anything")
    parser.add_argument("--repo", type=Path, default=Path("."), help="Repository root")
    args = parser.parse_args()

    failures = recover(args.snapshot, args.repo, args.to_commit, args.only, args.dry_run)
    if failures:
        log.error("Recovery completed with failures:")
        for f in failures:
            log.error("  - %s", f)
        log.info("Snapshot directory is left intact at %s", args.snapshot)
        return 1

    log.info("Recovery completed successfully. Snapshot directory left intact at %s", args.snapshot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
