import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

BACKUP_PATH = Path(__file__).resolve().parents[1] / "src/br_pre_commit/backup.py"
SPEC = importlib.util.spec_from_file_location("backup", BACKUP_PATH)
assert SPEC is not None and SPEC.loader is not None
backup = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = backup
SPEC.loader.exec_module(backup)

pytestmark = pytest.mark.unit


def test_backup_many_diffs_starts_all_files_concurrently(tmp_path, monkeypatch):
    async def exercise():
        all_started = asyncio.Event()
        started = []

        async def fake_backup(snapshot_dir, repo_root, prefix, path):
            started.append(path)
            if len(started) == 3:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=1)
            return {"original_path": path, "type": "patch"}

        monkeypatch.setattr(backup, "_backup_diff", fake_backup)
        entries = await backup._backup_many_diffs(tmp_path, tmp_path, backup.STAGED_PREFIX, ["c", "a", "b"])
        return started, entries

    started, entries = asyncio.run(exercise())

    assert set(started) == {"a", "b", "c"}
    assert [entry["original_path"] for entry in entries] == ["a", "b", "c"]


def test_decode_paths_preserves_spaces_and_non_ascii():
    assert backup._decode_paths("a file.txt\0δ.py\0".encode()) == ["a file.txt", "δ.py"]
