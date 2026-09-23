import asyncio

import pytest

import backup.__main__ as backup  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.backup]


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
        entries = await backup._backup_many_diffs(
            tmp_path, tmp_path, backup.backup_config.staged_prefix, ["c", "a", "b"]
        )
        return started, entries

    started, entries = asyncio.run(exercise())

    assert set(started) == {"a", "b", "c"}
    assert [entry["original_path"] for entry in entries] == ["a", "b", "c"]


# def test_decode_paths_preserves_spaces_and_non_ascii():
#     assert backup.decode_paths("a file.txt\0δ.py\0".encode()) == ["a file.txt", "δ.py"]


def test_write_patch_preserves_source_extension(tmp_path):
    entry = backup._write_patch(
        tmp_path, backup.backup_config.staged_prefix, "src/foo/__init__.py", b"diff --git a b\n"
    )
    assert entry["type"] == "patch"
    stored = tmp_path / entry["stored_path"]
    assert stored.exists()
    assert stored.name.startswith("__init__.py.")
    assert stored.name.endswith(".patch")
    # Format: __init__.py.<7-hex-hash>.patch
    stem = stored.name[: -len(".patch")]
    assert stem.startswith("__init__.py.")
    assert len(stem.split(".")[-1]) == 7


def test_write_patch_handles_extensionless_path(tmp_path):
    entry = backup._write_patch(tmp_path, backup.backup_config.staged_prefix, "Makefile", b"diff\n")
    assert entry["type"] == "patch"
    stored = tmp_path / entry["stored_path"]
    assert stored.exists()
    assert stored.name.startswith("Makefile.bin.")


def test_write_patch_dots_in_name_preserved(tmp_path):
    entry = backup._write_patch(tmp_path, backup.backup_config.staged_prefix, "src/foo.bar/baz.txt", b"diff\n")
    assert entry["type"] == "patch"
    stored = tmp_path / entry["stored_path"]
    assert stored.exists()
    assert stored.name.startswith("baz.txt.")


def test_copy_full_file_content_addressed_overwrites_same_version(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "archive_not_used_trash").mkdir(parents=True)
    full_backup_dir = tmp_path / "full"
    full_backup_dir.mkdir()

    source = repo_root / "src" / "archive_not_used_trash" / "legacy.py"
    source.write_text("v1\n", encoding="utf-8")

    e1 = backup._copy_full_file(full_backup_dir, repo_root, "src/archive_not_used_trash/legacy.py")
    e2 = backup._copy_full_file(full_backup_dir, repo_root, "src/archive_not_used_trash/legacy.py")
    assert e1 is not None and e2 is not None
    assert e1["stored_path"] == e2["stored_path"]
    assert (full_backup_dir / e1["stored_path"]).read_text() == "v1\n"

    source.write_text("v2-changed\n", encoding="utf-8")
    e3 = backup._copy_full_file(full_backup_dir, repo_root, "src/archive_not_used_trash/legacy.py")
    assert e3 is not None
    assert e3["stored_path"] != e1["stored_path"]
    assert (full_backup_dir / e3["stored_path"]).read_text() == "v2-changed\n"


def test_copy_full_file_hash_before_extension(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "archive_not_used_trash").mkdir(parents=True)
    full_backup_dir = tmp_path / "full"
    full_backup_dir.mkdir()

    source = repo_root / "src" / "archive_not_used_trash" / "legacy.py"
    source.write_text("content\n", encoding="utf-8")

    entry = backup._copy_full_file(full_backup_dir, repo_root, "src/archive_not_used_trash/legacy.py")
    assert entry is not None
    stored = full_backup_dir / entry["stored_path"]
    assert stored.exists()
    # Format: <flattened-stem>.<7-digit-hash>.<ext>  (extension is the last part)
    parts = stored.name.split(".")
    assert parts[-1] == "py"
    assert len(parts[-2]) == 7


def test_copy_full_file_extensionless(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "archive_not_used_trash").mkdir(parents=True)
    full_backup_dir = tmp_path / "full"
    full_backup_dir.mkdir()

    source = repo_root / "src" / "archive_not_used_trash" / "Makefile"
    source.write_text("all:\n", encoding="utf-8")

    entry = backup._copy_full_file(full_backup_dir, repo_root, "src/archive_not_used_trash/Makefile")
    assert entry is not None
    stored = full_backup_dir / entry["stored_path"]
    assert stored.exists()
    assert stored.name.endswith(".bin")
    assert len(stored.name.split(".")[-2]) == 7


def test_is_excluded_literal_and_regex():
    assert backup.is_excluded("src/archive_not_used_trash/foo.py", "archive_not_used_trash")
    assert not backup.is_excluded("src/foo.py", "archive_not_used_trash")
    assert backup.is_excluded("data/file.txt", "^(data|logs|\\.[^/]+)$")
    assert backup.is_excluded("logs/file.txt", "^(data|logs|\\.[^/]+)$")
    assert backup.is_excluded(".git/config", "^(data|logs|\\.[^/]+)$")
    assert not backup.is_excluded("src/foo.py", "^(data|logs|\\.[^/]+)$")


def test_backup_settings_defaults(tmp_path):
    defaults = {"full_backup_exclude_dir_regex": backup.backup_config.full_backup_exclude_dir_regex}
    assert defaults["full_backup_exclude_dir_regex"] == r"^(data|logs|archive_not_used_trash|\.[^/]+)$"
