"""Install the pre-commit hook."""

from __future__ import annotations

import argparse
import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import yaml

from precommit_wrapper.config import wrapper_config

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


def get_user_repo_root_from_git(cwd: Path) -> Path:
    # if cwd:
    #     return Path(cwd).resolve()
    user_repo_root = Path(
        subprocess.check_output(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            text=True,
        ).strip()
    ).resolve()
    print(f"\nRoot path of user repository: {user_repo_root}")
    if input("Do you confirm? [y/N]: ").strip().lower() not in ("y", "yes"):
        exit(1)
    return user_repo_root


def get_br_pre_commit_root_from_git() -> Path:
    br_pre_commit_repo_root = Path(
        subprocess.check_output(
            ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--show-toplevel"],
            text=True,
        ).strip()
    )
    print(f"\nRoot path of br_pre_commit repository: {br_pre_commit_repo_root}")
    if input("Do you confirm? [y/N]: ").strip().lower() not in ("y", "yes"):
        exit(1)
    return br_pre_commit_repo_root


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


def generate_posix_hook(br_pre_commit_repo_root: Path) -> str:
    active_venv = get_active_venv()
    assert isinstance(active_venv, Path)

    return (
        "#!/usr/bin/env sh\n"
        f"export BR_PRE_COMMIT_REPO_ROOT='{br_pre_commit_repo_root}'\n"
        f"export PYTHONPATH='{br_pre_commit_repo_root / 'src'}'\n\n"
        f"export PATH='{active_venv.parent}':\"$PATH\"\n\n"
        f'exec "{active_venv}" -m precommit_wrapper "$@"\n'
    )


def generate_powershell_hook(user_repo_root: Path, br_pre_commit_repo_root: Path) -> str:
    active_venv = get_active_venv()
    assert isinstance(active_venv, Path)

    return (
        "#!/bin/sh\n"
        f"export BR_PRE_COMMIT_REPO_ROOT='{br_pre_commit_repo_root}'\n"
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


def merge_project_config(user_repo_root: Path, br_pre_commit_repo_root: Path) -> list[str]:
    """Merge recognized br_pre_commit hooks into the project's .pre-commit-config.yaml.

    Adds the ``incremental-ratchet`` hook (LOC / complexity gate) if it is not
    already present.  Hook *ids* must match the recognized sets in
    ``src/precommit_wrapper/config.py``; unrecognized ids are rejected at
    commit time under the default ``unknown-hook-policy = "error"``.

    Returns a list of human-readable messages describing what was added.
    """
    config_path = user_repo_root / ".pre-commit-config.yaml"
    messages: list[str] = []

    if not config_path.exists():
        config_path.write_text("repos:\n", encoding="utf-8")
        messages.append(f"Created {config_path.relative_to(user_repo_root)}")

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {"repos": []}
    if not isinstance(config, dict):
        config = {"repos": []}
    repos = config.setdefault("repos", [])
    if not isinstance(repos, list):
        repos = []
        config["repos"] = repos

    local_repo = None
    for repo in repos:
        if isinstance(repo, dict) and repo.get("repo") == "local":
            local_repo = repo
            break
    if local_repo is None:
        local_repo = {"repo": "local", "hooks": []}
        repos.append(local_repo)

    hooks = local_repo.setdefault("hooks", [])
    if not isinstance(hooks, list):
        hooks = []
        local_repo["hooks"] = hooks

    existing_ids = {h.get("id") for h in hooks if isinstance(h, dict)}
    if "incremental-ratchet" not in existing_ids:
        hooks.append(wrapper_config.ratchet_hook_id)
        messages.append(f"Added 'incremental-ratchet' hook to {config_path.name}")

    config_path.write_text(
        yaml.dump(config, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return messages


def install(cwd: Path, force: bool, dry_run: bool) -> int:
    missing = verify_requirements()
    if missing:
        joined = ", ".join(missing)
        print(
            f"ERROR: missing required package(s) for br_pre_commit: {joined}. "
            f"Install them in the active environment and re-run."
        )
        return 1

    user_repo_root = get_user_repo_root_from_git(cwd)
    br_pre_commit_repo_root = get_br_pre_commit_root_from_git()
    git_dir = get_git_dir(user_repo_root)
    hook_path = git_dir / "hooks" / "pre-commit"

    if is_wsl():
        hook_content = generate_posix_hook(br_pre_commit_repo_root)
    elif sys.platform == "win32":
        hook_content = generate_powershell_hook(user_repo_root, br_pre_commit_repo_root)
    else:
        hook_content = generate_posix_hook(br_pre_commit_repo_root)

    if dry_run:
        print(f"Would write to {hook_path}")
        print(hook_content)
        return 0

    if hook_path.exists() and not force:
        print(f"Hook already exists at {hook_path} (use --force to sliently overwrite)")
        if input("Force install? (y/n) ").lower() not in ["y", "yes"]:
            return 1

    hook_path.write_text(hook_content, encoding="utf-8")
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Installed {hook_path}")

    if not dry_run:
        for msg in merge_project_config(user_repo_root, br_pre_commit_repo_root):
            print(msg)
    return 0


def main() -> int:
    venv_path = get_active_venv()

    if venv_path:
        print(f"Active virtual environment: {venv_path}")
    else:
        print("No active virtual environment!")
        return -1

    parser = argparse.ArgumentParser(prog="br_pre_commit.install")
    parser.add_argument("user_repo_path", metavar="user-repo-path", nargs="?", default=Path.cwd())
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    user_repo_root = Path(args.user_repo_path).resolve() if args.user_repo_path else Path.cwd().resolve()

    if args.dry_run:
        return install(
            user_repo_root,
            args.force,
            dry_run=True,
        )

    answer = input("\nConfirm to continue? [y/N]: ").strip().lower()
    if answer not in {"y", "yes"}:
        print("Installation cancelled.")
        return 0

    return install(
        user_repo_root,
        args.force,
        dry_run=False,
    )


if __name__ == "__main__":
    sys.exit(main())
