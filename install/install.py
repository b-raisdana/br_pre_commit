"""Install the pre-commit hook."""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path


# def get_tool_root() -> Path:
#     return Path(__file__).resolve().parent.parent


def get_user_repo_root(repo_path: str | None) -> Path:
    if repo_path:
        return Path(repo_path).resolve()
    result = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
        ).strip())
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
    result = Path(subprocess.check_output(
        ["git", "-C", str(repo_root), "rev-parse", "--absolute-git-dir"],
        text=True,
    ).strip())
    return result


def is_wsl() -> bool:
    return "WSL_DISTRO_NAME" in os.environ


def generate_posix_hook(repo_root: Path, br_pre_commit_repo_root: Path) -> str:
    return (
        f"#!/usr/bin/env sh\n"
        f"export BR_PRE_COMMIT_REPO_ROOT={repo_root}\n"
        f'export PYTHONPATH="{br_pre_commit_repo_root}/src"\n'
        'exec python -m precommit_wrapper "$@"\n'
    )


def generate_powershell_hook(repo_root: Path, br_pre_commit_repo_root: Path) -> str:
    return (
        "#!/bin/sh\n"
        f"export BR_PRE_COMMIT_REPO_ROOT='{br_pre_commit_repo_root}'\n"
        f"export PYTHONPATH='{br_pre_commit_repo_root/ 'src'}'\n\n"

        "if command -v pwsh > /dev/null 2>&1; then\n"
        "   exec pwsh -NoProfile -Command 'python -m precommit_wrapper $args' -- \"$@\"\n"
        "elif command -v powershell > /dev/null 2>&1; then\n"
        "   exec powershell -NoProfile -Command 'python -m precommit_wrapper $args' -- \"$@\"\n"
        "else\n"
        "   echo \"ERROR: PowerShell is required.\" >&2\n"
        "   exit 1\n"
        "fi\n"
    )


def install(repo_path: str | None, force: bool, dry_run: bool) -> int:
    # tool_root = get_tool_root()
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
    parser = argparse.ArgumentParser(prog="br_pre_commit.install")
    parser.add_argument("repo_path", nargs="?", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return install(args.repo_path, args.force, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
