"""Install the pre-commit hook."""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path


def get_tool_root() -> Path:
    return Path(__file__).resolve().parent.parent


def get_repo_root(repo_path: str | None) -> Path:
    if repo_path:
        return Path(repo_path).resolve()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip()).resolve()


def get_git_dir(repo_root: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip()).resolve()


def is_wsl() -> bool:
    return "WSL_DISTRO_NAME" in os.environ


def generate_posix_hook(repo_root: Path, tool_root: Path) -> str:
    return (
        f"#!/usr/bin/env sh\n"
        f"export BR_PRE_COMMIT_REPO_ROOT={repo_root}\n"
        f'export PYTHONPATH="{tool_root}/src"\n'
        'exec python -m precommit_wrapper "$@"\n'
    )


def generate_powershell_hook(repo_root: Path, tool_root: Path) -> str:
    return (
        "#!/usr/bin/env pwsh\n"
        f"$env:BR_PRE_COMMIT_REPO_ROOT = '{repo_root}'\n"
        f"$env:PYTHONPATH = '{tool_root}/src'\n"
        "python -m precommit_wrapper @args\n"
    )


def install(repo_path: str | None, force: bool, dry_run: bool) -> int:
    tool_root = get_tool_root()
    repo_root = get_repo_root(repo_path)
    git_dir = get_git_dir(repo_root)
    hook_path = git_dir / "hooks" / "pre-commit"

    if is_wsl():
        hook_content = generate_posix_hook(repo_root, tool_root)
    elif sys.platform == "win32":
        hook_content = generate_powershell_hook(repo_root, tool_root)
    else:
        hook_content = generate_posix_hook(repo_root, tool_root)

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
