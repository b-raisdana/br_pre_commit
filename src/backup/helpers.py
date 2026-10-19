"""Helper functions extracted from __main__ to keep it under LOC cap."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .common import content_hash
from .models import Manifest

log = logging.getLogger("backup")


def _attempt_timestamp() -> str:
    """Human-readable timestamp of the backup attempt, with milliseconds."""
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S.%f")[:-3]


def _entry_fullpath(entry: dict[str, str], base_dir: Path) -> str:
    stored = entry.get("stored_path")
    if not stored or stored == "None":
        return ""
    return str(base_dir / stored)


def _write_attempt_manifest(
    manifest_dir: Path,
    attempt_ts: str,
    snapshot_dir: Path,
    full_backup_dir: Path,
    manifest: Manifest,
) -> Path:
    files: list[str] = []
    for entries in (manifest.staged, manifest.unstaged, manifest.untracked):
        for entry in entries:
            full = _entry_fullpath(entry, snapshot_dir)
            if full:
                files.append(full)
    for entry in manifest.full_backups:
        full = _entry_fullpath(entry, full_backup_dir)
        if full:
            files.append(full)

    payload = {
        "attempt_timestamp": attempt_ts,
        "branch": manifest.branch,
        "commit_hash": manifest.commit_hash,
        "snapshot_dir": manifest.snapshot_dir,
        "files": files,
    }
    manifest_path = manifest_dir / f"{attempt_ts}.json"
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def _write_manifest(path: Path, manifest: Manifest) -> None:
    path.write_text(json.dumps(asdict(manifest), indent=2) + "\n", encoding="utf-8")


def _write_patch(snapshot_dir: Path, prefix: str, path: str, patch: bytes) -> dict[str, str]:
    entry = {"original_path": path}
    try:
        content = patch + b"\n"
        source_path = Path(path)
        ext = source_path.suffix.lstrip(".") or "bin"
        stored_path = Path(prefix) / source_path.with_name(f"{source_path.stem}.{ext}.{content_hash(content)}.patch")
        destination = snapshot_dir / stored_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        entry.update(type="patch", stored_path=stored_path.as_posix())
    except Exception as exc:
        log.exception("Failed to backup %s %s: %s", prefix, path, exc)
        entry.update(type="failed", error=str(exc))
    return entry


def _is_text_file(path: Path) -> bool:
    try:
        path.read_text(encoding="utf-8")
        return True
    except UnicodeDecodeError:
        return False
    except Exception:
        return False


def _copy_full_file(
    full_backup_dir: Path, user_repo_root: Path, path: str, *, text_only: bool = False
) -> dict[str, str] | None:
    source = user_repo_root / path
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
        hash_suffix = content_hash(content)
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
