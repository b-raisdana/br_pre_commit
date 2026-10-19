from pathlib import Path

import pytest

from src.backup.recover import _recover_files

pytestmark = [pytest.mark.unit, pytest.mark.backup]


def test_recover_files_copies_nested_destinations_and_filters_type(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "payload").write_bytes(b"restored")
    repo = tmp_path / "repo"
    entries = [
        {"original_path": "nested/file.bin", "stored_path": "payload", "type": "full"},
        {"original_path": "ignored.bin", "stored_path": "missing", "type": "patch"},
    ]

    failures = _recover_files(repo, source, entries, "full", False, required_type="full")

    assert failures == []
    assert (repo / "nested/file.bin").read_bytes() == b"restored"
    assert not (repo / "ignored.bin").exists()


def test_recover_files_reports_missing_file_and_dry_run_does_not_copy(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "payload").write_text("data", encoding="utf-8")
    repo = tmp_path / "repo"
    entries = [
        {"original_path": "nested/file.txt", "stored_path": "payload"},
        {"original_path": "missing.txt", "stored_path": "absent"},
        {"original_path": "failed.txt", "stored_path": "None"},
    ]

    failures = _recover_files(repo, source, entries, "untracked", True)

    assert failures == [f"untracked missing.txt: missing {source / 'absent'}"]
    assert not (repo / "nested/file.txt").exists()


def test_recover_files_captures_destination_write_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "payload").write_bytes(b"data")
    repo = tmp_path / "repo"
    monkeypatch.setattr(Path, "write_bytes", lambda *_args: (_ for _ in ()).throw(OSError("read only")))

    failures = _recover_files(
        repo,
        source,
        [{"original_path": "file.txt", "stored_path": "payload"}],
        "untracked",
        False,
    )

    assert failures == ["untracked file.txt: read only"]
