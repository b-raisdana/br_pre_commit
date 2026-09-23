import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.backup]

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKUP_MODULE = "src.backup"
RECOVER_MODULE = "src.backup.recover"
_TEST_ENV = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}


def _init_git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("initial\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def _run_backup(repo_root: Path) -> Path:
    subprocess.run(
        [sys.executable, "-m", BACKUP_MODULE, "--repo", str(repo_root)],
        capture_output=True,
        text=True,
        check=True,
        cwd=repo_root,
        env=_TEST_ENV,
    )
    snapshot_dirs = list((repo_root / "logs" / "pre-commit" / "backup-patches").iterdir())
    assert snapshot_dirs, "No snapshot directory created"
    return sorted(snapshot_dirs)[-1]


def _run_recover(
    snapshot_dir: Path, repo_root: Path, extra_args: list[str] | None = None
) -> subprocess.CompletedProcess:
    args = [sys.executable, "-m", RECOVER_MODULE, "--snapshot", str(snapshot_dir), "--repo", str(repo_root)]
    if extra_args:
        args.extend(extra_args)
    return subprocess.run(args, capture_output=True, text=True, cwd=repo_root, env=_TEST_ENV)


# ---- (a) staged + unstaged round-trip ----


def test_recover_staged_and_unstaged_roundtrip(tmp_path: Path):
    _init_git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-b", "feature/roundtrip"], cwd=tmp_path, check=True, capture_output=True)

    (tmp_path / "target.txt").write_text("line1\nline2\n")
    subprocess.run(["git", "add", "target.txt"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "target.txt").write_text("line1\nline2\nline3-UNSTAGED\n")

    snapshot_dir = _run_backup(tmp_path)

    # Wipe working tree to simulate a bad state
    (tmp_path / "target.txt").write_text("CORRUPTED\n")
    subprocess.run(["git", "checkout", "--", "target.txt"], cwd=tmp_path, check=True, capture_output=True)

    result = _run_recover(snapshot_dir, tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "target.txt").read_text() == "line1\nline2\nline3-UNSTAGED\n"

    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert "target.txt" in staged
    unstaged = subprocess.run(
        ["git", "diff", "--name-only"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert "target.txt" in unstaged


# ---- (b) binary round-trip ----


def test_recover_binary_roundtrip(tmp_path: Path):
    _init_git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-b", "feature/binary"], cwd=tmp_path, check=True, capture_output=True)

    blob = bytes(range(256))
    (tmp_path / "data.bin").write_bytes(blob)
    subprocess.run(["git", "add", "data.bin"], cwd=tmp_path, check=True, capture_output=True)

    snapshot_dir = _run_backup(tmp_path)

    (tmp_path / "data.bin").write_bytes(b"corrupted")
    subprocess.run(["git", "checkout", "--", "data.bin"], cwd=tmp_path, check=True, capture_output=True)

    result = _run_recover(snapshot_dir, tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "data.bin").read_bytes() == blob


def test_backup_keeps_changed_patches_and_refreshes_identical_patch(tmp_path: Path):
    _init_git_repo(tmp_path)
    (tmp_path / "target.txt").write_text("first\n")
    subprocess.run(["git", "add", "target.txt"], cwd=tmp_path, check=True, capture_output=True)

    snapshot_dir = _run_backup(tmp_path)
    first_manifest = json.loads((snapshot_dir / "manifest.json").read_text())
    first_patch = snapshot_dir / first_manifest["staged"][0]["stored_path"]
    first_mtime = first_patch.stat().st_mtime_ns

    import time

    time.sleep(0.01)
    _run_backup(tmp_path)
    assert first_patch.stat().st_mtime_ns > first_mtime

    (tmp_path / "target.txt").write_text("second\n")
    subprocess.run(["git", "add", "target.txt"], cwd=tmp_path, check=True, capture_output=True)
    _run_backup(tmp_path)

    patches = list((snapshot_dir / "staged").glob("target.*.patch"))
    assert len(patches) == 2
    # Stored name is target.<ext>.<hash>.patch; the hash is the 3rd dot-separated part.
    assert all(len(patch.stem.split(".")[2]) == 7 for patch in patches)


# ---- (c) untracked round-trip ----


def test_recover_untracked_roundtrip(tmp_path: Path):
    _init_git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-b", "feature/untracked"], cwd=tmp_path, check=True, capture_output=True)

    (tmp_path / "new_file.txt").write_text("untracked content\n")

    snapshot_dir = _run_backup(tmp_path)

    (tmp_path / "new_file.txt").unlink()

    result = _run_recover(snapshot_dir, tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "new_file.txt").exists()
    assert (tmp_path / "new_file.txt").read_text() == "untracked content\n"


# ---- (d) diverged tree fails clearly ----


def test_recover_fails_clearly_on_diverged_tree(tmp_path: Path):
    _init_git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-b", "feature/diverged"], cwd=tmp_path, check=True, capture_output=True)

    (tmp_path / "target.txt").write_text("line1\nline2\n")
    subprocess.run(["git", "add", "target.txt"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "target.txt").write_text("line1\nline2\nline3-UNSTAGED\n")

    snapshot_dir = _run_backup(tmp_path)

    # Change the unstaged file on disk so the patch context no longer matches
    (tmp_path / "target.txt").write_text("COMPLETELY DIFFERENT\n")

    result = _run_recover(snapshot_dir, tmp_path)
    assert result.returncode == 1
    assert "unstaged target.txt" in result.stderr


# ---- dry-run ----


def test_recover_dry_run(tmp_path: Path):
    _init_git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-b", "feature/dryrun"], cwd=tmp_path, check=True, capture_output=True)

    (tmp_path / "target.txt").write_text("line1\n")
    subprocess.run(["git", "add", "target.txt"], cwd=tmp_path, check=True, capture_output=True)

    snapshot_dir = _run_backup(tmp_path)

    result = _run_recover(snapshot_dir, tmp_path, ["--dry-run"])
    assert result.returncode == 0, result.stderr
    assert "[dry-run]" in result.stderr
    assert (tmp_path / "target.txt").read_text() == "line1\n"


# ---- manifest validation ----


def test_recover_refuses_missing_manifest(tmp_path: Path):
    result = _run_recover(tmp_path / "does-not-exist", tmp_path)
    assert result.returncode == 1
    assert "manifest.json not found" in result.stderr


def test_recover_only_staged(tmp_path: Path):
    _init_git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-b", "feature/only-staged"], cwd=tmp_path, check=True, capture_output=True)

    (tmp_path / "staged.txt").write_text("staged\n")
    subprocess.run(["git", "add", "staged.txt"], cwd=tmp_path, check=True, capture_output=True)

    (tmp_path / "unstaged.txt").write_text("unstaged\n")

    snapshot_dir = _run_backup(tmp_path)

    (tmp_path / "staged.txt").write_text("gone\n")
    (tmp_path / "unstaged.txt").write_text("gone\n")

    result = _run_recover(snapshot_dir, tmp_path, ["--only", "staged"])
    assert result.returncode == 0, result.stderr
    # Staged recovery updates the index only; working tree is untouched
    assert (tmp_path / "staged.txt").read_text() == "gone\n"
    assert (tmp_path / "unstaged.txt").read_text() == "gone\n"
    index_content = subprocess.run(
        ["git", "show", ":staged.txt"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout
    assert index_content == "staged\n"
    assert (tmp_path / "unstaged.txt").read_text() == "gone\n"


def test_recover_to_commit(tmp_path: Path):
    _init_git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-b", "feature/to-commit"], cwd=tmp_path, check=True, capture_output=True)

    (tmp_path / "file.txt").write_text("v1\n")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add file"], cwd=tmp_path, check=True, capture_output=True)

    snapshot_dir = _run_backup(tmp_path)

    (tmp_path / "file.txt").write_text("v2\n")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "change file"], cwd=tmp_path, check=True, capture_output=True)

    result = _run_recover(snapshot_dir, tmp_path, ["--to-commit"])
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "file.txt").read_text() == "v1\n"
