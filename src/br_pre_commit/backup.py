#!/usr/bin/env python3
"""Create a read-only working-state snapshot with concurrent Git and file I/O."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import sys
import tomllib
import zlib
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TypedDict

logging.basicConfig(level=logging.DEBUG, format="%(message)s")
log = logging.getLogger("backup")

sys.path.insert(0, str(Path(__file__).parent))

from models import Manifest  # noqa: E402

STAGED_PREFIX = "staged"
UNSTAGED_PREFIX = "unstaged"
UNTRACKED_PREFIX = "untracked"
FULL_BACKUP_DIR = "full_backup"

_DEFAULTS_PATH = Path(__file__).resolve().parents[2] / "defaults.toml"


class BackupSettings(TypedDict, total=False):
    exclude_dir: str


def _backup_settings(repo_root: Path) -> BackupSettings:
    """Load backup settings: defaults overlaid by project .br-pre-commit.toml."""
    settings: BackupSettings = {"exclude_dir": "archive_not_used_trash"}
    project_path = repo_root / ".br-pre-commit.toml"
    if not project_path.exists():
        return settings
    data = tomllib.loads(project_path.read_text(encoding="utf-8"))
    section = data.get("backup")
    if isinstance(section, dict) and "exclude-dir" in section:
        settings["exclude_dir"] = str(section["exclude-dir"])
    return settings


def _flatten_path(path: str) -> str:
    return path.replace("/", "_").replace("\\", "_")


def _content_hash(content: bytes) -> str:
    """Return a short, non-cryptographic content identifier."""
    return f"{zlib.crc32(content) & 0xFFFFFFFF:08x}"[-7:]


async def _git(repo_root: Path, *args: str) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=repo_root, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        message = stderr.decode("utf-8", errors="replace").strip()
        log.error("git %s failed: %s", " ".join(args), message)
        raise subprocess_error(proc.returncode, args, stdout, stderr)
    return stdout


def subprocess_error(returncode: int, args: tuple[str, ...], stdout: bytes, stderr: bytes) -> RuntimeError:
    return RuntimeError(f"git {' '.join(args)} exited {returncode}: {stderr.decode('utf-8', errors='replace').strip()}")


def _decode_paths(output: bytes) -> list[str]:
    return [path.decode("utf-8", errors="surrogateescape") for path in output.split(b"\0") if path]


def _write_patch(snapshot_dir: Path, prefix: str, path: str, patch: bytes) -> dict[str, str]:
    entry = {"original_path": path}
    try:
        content = patch + b"\n"
        source_path = Path(path)
        ext = source_path.suffix.lstrip(".") or "bin"
        # Stored name: <prefix>/<dir>/<stem>.<ext>.<hash>.patch
        # e.g. src/foo/__init__.py.d30c167.patch
        stored_path = Path(prefix) / source_path.with_name(f"{source_path.stem}.{ext}.{_content_hash(content)}.patch")
        destination = snapshot_dir / stored_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        entry.update(type="patch", stored_path=stored_path.as_posix())
    except Exception as exc:
        log.exception("Failed to backup %s %s: %s", prefix, path, exc)
        entry.update(type="failed", error=str(exc))
    return entry


def _copy_full_file(full_backup_dir: Path, repo_root: Path, path: str) -> dict[str, str] | None:
    """Copy an excluded-path file verbatim into the content-addressed full-backup store.

    The stored name is ``<relpath-flattened>.<ext>.<7-digit-content-hash>`` so that
    different versions of the same file keep distinct copies and identical versions
    overwrite each other. e.g. ``src_archive_not_used_trash_legacy.py.abc1234``.
    """
    source = repo_root / path
    if not source.is_file():
        return None
    try:
        content = source.read_bytes()
    except Exception as exc:
        log.exception("Failed to read %s for full backup: %s", path, exc)
        return {"original_path": path, "type": "failed", "error": str(exc)}
    try:
        flat = _flatten_path(path)
        ext = source.suffix.lstrip(".") or "bin"
        stored_path = f"{flat}.{ext}.{_content_hash(content)}"
        destination = full_backup_dir / stored_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return {"original_path": path, "type": "full", "stored_path": stored_path}
    except Exception as exc:
        log.exception("Failed to backup full file %s: %s", path, exc)
        return {"original_path": path, "type": "failed", "error": str(exc)}


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


def _write_manifest(path: Path, manifest: Manifest) -> None:
    path.write_text(json.dumps(asdict(manifest), indent=2) + "\n", encoding="utf-8")


def _snapshot_size(snapshot_dir: Path) -> int:
    return sum(path.stat().st_size for path in snapshot_dir.rglob("*") if path.is_file())


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


async def take_snapshot_async(repo_root: Path) -> Manifest:
    log.debug("Taking snapshot %s...", repo_root)
    branch_raw, commit_raw, staged_raw, unstaged_raw, untracked_raw = await asyncio.gather(
        _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
        _git(repo_root, "rev-parse", "HEAD"),
        _git(repo_root, "diff", "--cached", "--name-only", "-z"),
        _git(repo_root, "diff", "--name-only", "-z"),
        _git(repo_root, "ls-files", "--others", "--exclude-standard", "-z"),
    )
    branch = branch_raw.decode().strip()
    commit_hash = commit_raw.decode().strip()
    snapshot_dir = get_snapshot_dir(branch, commit_hash, repo_root)

    settings = _backup_settings(repo_root)
    exclude_dir = settings.get("exclude_dir", "archive_not_used_trash")

    staged_paths = _decode_paths(staged_raw)
    unstaged_paths = _decode_paths(unstaged_raw)
    untracked_paths = _decode_paths(untracked_raw)

    def _split(paths: list[str]) -> tuple[list[str], list[str]]:
        keep: list[str] = []
        full: list[str] = []
        for path in paths:
            (full if _is_excluded(path, exclude_dir) else keep).append(path)
        return keep, full

    staged_keep, staged_full = _split(staged_paths)
    unstaged_keep, unstaged_full = _split(unstaged_paths)
    untracked_keep, untracked_full = _split(untracked_paths)

    full_backup_dir = _get_full_backup_dir(repo_root)
    full_entries = await asyncio.gather(
        *(
            asyncio.to_thread(_copy_full_file, full_backup_dir, repo_root, path)
            for path in staged_full + unstaged_full + untracked_full
        )
    )
    full_backups = sorted(
        (entry for entry in full_entries if entry is not None),
        key=lambda entry: entry["original_path"],
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
    parser.add_argument("--print-manifest-json", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_main_async(args.repo.resolve(), print_manifest_json=args.print_manifest_json))


if __name__ == "__main__":
    result = main()
    log.debug("Backup script exited with code %d", result)
    sys.exit(result)
