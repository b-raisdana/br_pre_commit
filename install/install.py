"""Install the pre-commit hook."""

from __future__ import annotations

import argparse
import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

# Import names of the third-party packages br_pre_commit needs in the active
# environment. Mirrors requirements.txt (pip names -> import names):
#   pyyaml -> yaml, pre-commit -> pre_commit, radon -> radon, ruff -> ruff,
#   mypy -> mypy, pytest -> pytest, pytest-asyncio -> pytest_asyncio.
# Everything else in src/ is stdlib (git is invoked via subprocess, no library).
REQUIRED_PACKAGES = ["yaml", "pre_commit", "radon", "ruff", "mypy", "pytest", "pytest_asyncio"]


def get_active_venv() -> Path | None:
    venv_ = os.environ.get("VIRTUAL_ENV") or os.environ.get("CONDA_PREFIX")

    if not venv_:
        return None

    venv_path = Path(venv_)

    if os.name == "nt":
        return venv_path / "python.exe" if "CONDA_PREFIX" in os.environ else venv_path / "Scripts" / "python.exe"

    return venv_path / "bin" / "python"


def get_user_repo_root(repo_path: str | None) -> Path:
    if repo_path:
        return Path(repo_path).resolve()
    result = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
        ).strip()
    )
    return result


def get_br_pre_commit_root():
    result = Path(
        subprocess.check_output(
            ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--show-toplevel"],
            text=True,
        ).strip()
    )
    return result


def get_git_dir(repo_root: Path) -> Path:
    result = Path(
        subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--absolute-git-dir"],
            text=True,
        ).strip()
    )
    return result


def is_wsl() -> bool:
    return "WSL_DISTRO_NAME" in os.environ


def generate_posix_hook(user_repo_root: Path, br_pre_commit_repo_root: Path) -> str:
    active_venv = get_active_venv()
    assert isinstance(active_venv, Path)

    return (
        "#!/usr/bin/env sh\n"
        f"export BR_PRE_COMMIT_REPO_ROOT='{user_repo_root}'\n"
        f"export PYTHONPATH='{br_pre_commit_repo_root / 'src'}'\n\n"
        f"export PATH='{active_venv.parent}':\"$PATH\"\n\n"
        f'exec "{active_venv}" -m precommit_wrapper "$@"\n'
    )


def generate_powershell_hook(user_repo_root: Path, br_pre_commit_repo_root: Path) -> str:
    active_venv = get_active_venv()
    assert isinstance(active_venv, Path)

    return (
        "#!/bin/sh\n"
        f"export BR_PRE_COMMIT_REPO_ROOT='{user_repo_root}'\n"
        f"export PYTHONPATH='{br_pre_commit_repo_root / 'src'}'\n"
        f"export PATH='{active_venv.parent}':\"$PATH\"\n\n"
        "if command -v pwsh > /dev/null 2>&1; then\n"
        f""" exec pwsh -NoProfile -Command '& "{active_venv}" -m precommit_wrapper $args' -- "$@"\n"""
        "elif command -v powershell > /dev/null 2>&1; then\n"
        f""" exec powershell -NoProfile -Command '& "{active_venv}" -m precommit_wrapper $args' -- "$@"\n"""
        "else\n"
        ' echo "ERROR: PowerShell is required." >&2\n'
        " exit 1\n"
        "fi\n"
    )


def verify_requirements() -> list[str]:
    """Check that every third-party package br_pre_commit needs is importable.

    Returns a list of missing package names (empty when all are satisfied).
    """
    missing: list[str] = []
    for package in REQUIRED_PACKAGES:
        if importlib.util.find_spec(package) is None:
            missing.append(package)
    return missing


def install(repo_path: str | None, force: bool, dry_run: bool) -> int:
    missing = verify_requirements()
    if missing:
        joined = ", ".join(missing)
        print(
            f"ERROR: missing required package(s) for br_pre_commit: {joined}. "
            f"Install them in the active environment and re-run."
        )
        return 1

    user_repo_root = get_user_repo_root(repo_path)
    br_pre_commit_repo_root = get_br_pre_commit_root()
    git_dir = get_git_dir(user_repo_root)
    hook_path = git_dir / "hooks" / "pre-commit"

    if is_wsl():
        hook_content = generate_posix_hook(user_repo_root, br_pre_commit_repo_root)
    elif sys.platform == "win32":
        hook_content = generate_powershell_hook(user_repo_root, br_pre_commit_repo_root)
    else:
        hook_content = generate_posix_hook(user_repo_root, br_pre_commit_repo_root)

    if dry_run:
        print(f"Would write to {hook_path}")
        print(hook_content)
        return 0

    if hook_path.exists() and not force:
        print(f"Hook already exists at {hook_path} (use --force to overwrite)")
        return 1

    hook_path.write_text(hook_content, encoding="utf-8")
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Installed {hook_path}")
    return 0


def main() -> int:
    venv_path = get_active_venv()

    if venv_path:
        print(f"Active virtual environment: {venv_path}")
    else:
        print("No active virtual environment!")
        return -1

    parser = argparse.ArgumentParser(prog="br_pre_commit.install")
    parser.add_argument("repo_path", nargs="?", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return install(args.repo_path, args.force, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
