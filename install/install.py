"""Install the pre-commit hook."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import os
import shlex
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

# Import names of the third-party packages br_pre_commit needs in the active
# environment. Mirrors requirements.txt (pip names -> import names):
#   pyyaml -> yaml, pre-commit -> pre_commit, radon -> radon, ruff -> ruff,
#   mypy -> mypy, pytest -> pytest, pydantic-settings -> pydantic_settings.
# Everything else in src/ is stdlib (git is invoked via subprocess, no library).
REQUIRED_PACKAGES = ["yaml", "pre_commit", "radon", "ruff", "mypy", "pytest", "pydantic_settings"]

_SHARED_MODULE_ENTRIES = {
    "check-pandera-decorator": "python -m check_pandera_decorator",
    "incremental-ratchet": "python -m ratchet",
    "no-commit-to-main": "python -m check_no_commit_to_main",
    "no-object-annotations": "python -m check_no_object_annotations",
    "sync-skill-files": "python -m sync_skills",
}
_SHARED_PYPROJECT_SECTIONS = ("wrapper", "ratchet", "backup")


def get_active_venv() -> Path | None:
    venv_ = os.environ.get("VIRTUAL_ENV") or os.environ.get("CONDA_PREFIX")

    if not venv_:
        return None

    venv_path = Path(venv_)

    if os.name == "nt":
        return venv_path / "python.exe" if "CONDA_PREFIX" in os.environ else venv_path / "Scripts" / "python.exe"

    return venv_path / "bin" / "python"


def get_user_repo_root_from_git(repo_path: str | None = None) -> Path:
    if repo_path:
        return Path(repo_path).resolve()
    result = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
        ).strip()
    )
    return result


def get_br_pre_commit_root_from_git():
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
        f"export BR_PRE_COMMIT_REPO_ROOT={shlex.quote(str(br_pre_commit_repo_root))}\n"
        f"export USER_REPO_ROOT={shlex.quote(str(user_repo_root))}\n"
        f"export PYTHONPATH={shlex.quote(str(br_pre_commit_repo_root / 'src'))}\n\n"
        f'export PATH={shlex.quote(str(active_venv.parent))}:"$PATH"\n\n'
        f'exec {shlex.quote(str(active_venv))} -m precommit_wrapper "$@"\n'
    )


def generate_powershell_hook(user_repo_root: Path, br_pre_commit_repo_root: Path) -> str:
    active_venv = get_active_venv()
    assert isinstance(active_venv, Path)

    return (
        "#!/bin/sh\n"
        f"export BR_PRE_COMMIT_REPO_ROOT={shlex.quote(str(br_pre_commit_repo_root))}\n"
        f"export USER_REPO_ROOT={shlex.quote(str(user_repo_root))}\n"
        f"export PYTHONPATH={shlex.quote(str(br_pre_commit_repo_root / 'src'))}\n"
        f'export PATH={shlex.quote(str(active_venv.parent))}:"$PATH"\n\n'
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
    """Merge the master hook list while preserving project-specific settings."""
    config_path = user_repo_root / ".pre-commit-config.yaml"
    master_config_path = br_pre_commit_repo_root / ".pre-commit-config.yaml"
    messages: list[str] = []

    master_config = _load_pre_commit_config(master_config_path)
    if config_path.exists():
        config = _load_pre_commit_config(config_path)
    else:
        config = {key: copy.deepcopy(value) for key, value in master_config.items() if key != "repos"}
        config["repos"] = []
        messages.append(f"Created {config_path.relative_to(user_repo_root)}")

    repos = config["repos"]
    for master_repo in master_config["repos"]:
        repo_address = master_repo["repo"]
        project_repo = next((repo for repo in repos if repo.get("repo") == repo_address), None)
        if project_repo is None:
            repos.append(copy.deepcopy(master_repo))
            messages.append(f"Added hook repository '{repo_address}'")
            continue

        project_hooks = project_repo["hooks"]
        project_hooks_by_id = {hook["id"]: hook for hook in project_hooks}
        for master_hook in master_repo["hooks"]:
            hook_id = master_hook["id"]
            project_hook = project_hooks_by_id.get(hook_id)
            if project_hook is None:
                project_hooks.append(copy.deepcopy(master_hook))
                messages.append(f"Added hook '{hook_id}'")
                continue

            if "stages" not in project_hook:
                project_hook["stages"] = copy.deepcopy(master_hook["stages"])
                messages.append(f"Added master switch for '{hook_id}'")

            canonical_entry = _SHARED_MODULE_ENTRIES.get(hook_id)
            if canonical_entry is not None and project_hook.get("entry") != canonical_entry:
                project_hook["entry"] = canonical_entry
                messages.append(f"Updated shared module entry for '{hook_id}'")

    config_path.write_text(
        yaml.dump(config, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return messages


def merge_project_pyproject(user_repo_root: Path, br_pre_commit_repo_root: Path) -> list[str]:
    """Append missing shared settings sections without changing project settings."""
    project_path = user_repo_root / "pyproject.toml"
    master_path = br_pre_commit_repo_root / "pyproject.toml"
    project_text = project_path.read_text(encoding="utf-8") if project_path.exists() else ""
    project_data = tomllib.loads(project_text) if project_text.strip() else {}
    with master_path.open("rb") as master_file:
        master_data = tomllib.load(master_file)

    project_settings = project_data.get("tool", {}).get("br_pre_commit", {})
    master_settings = master_data["tool"]["br_pre_commit"]
    sections_to_add: list[str] = []
    messages: list[str] = []
    for section_name in _SHARED_PYPROJECT_SECTIONS:
        if section_name in project_settings:
            continue
        section_values = copy.deepcopy(master_settings[section_name])
        if section_name == "ratchet" and (user_repo_root / "app").is_dir() and not (user_repo_root / "src").is_dir():
            section_values["target"] = "app"
        lines = [f"[tool.br_pre_commit.{section_name}]"]
        lines.extend(f"{key} = {_toml_value(value)}" for key, value in section_values.items())
        sections_to_add.append("\n".join(lines))
        messages.append(f"Added [tool.br_pre_commit.{section_name}] settings")

    if sections_to_add:
        separator = "" if not project_text or project_text.endswith("\n") else "\n"
        prefix = "" if not project_text else "\n"
        project_path.write_text(
            f"{project_text}{separator}{prefix}" + "\n\n".join(sections_to_add) + "\n",
            encoding="utf-8",
        )
    return messages


def _toml_value(value: str | int | bool | list[str]) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "[" + ", ".join(repr(item) for item in value) + "]"
    raise TypeError(f"unsupported shared TOML value: {value!r}")


def _load_pre_commit_config(config_path: Path) -> dict:
    """Load and validate the structure needed for a safe hook merge."""
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("repos"), list):
        raise ValueError(f"{config_path} must contain a top-level 'repos' list")

    for repo in config["repos"]:
        if not isinstance(repo, dict) or not isinstance(repo.get("repo"), str):
            raise ValueError(f"{config_path} contains an invalid repository definition")
        if not isinstance(repo.get("hooks"), list):
            raise ValueError(f"repository '{repo['repo']}' in {config_path} must contain a 'hooks' list")
        for hook in repo["hooks"]:
            if not isinstance(hook, dict) or not isinstance(hook.get("id"), str):
                raise ValueError(f"repository '{repo['repo']}' in {config_path} contains an invalid hook")
    return config


def install(repo_path: str | None, force: bool, dry_run: bool) -> int:
    missing = verify_requirements()
    if missing:
        joined = ", ".join(missing)
        print(
            f"ERROR: missing required package(s) for br_pre_commit: {joined}. "
            f"Install them in the active environment and re-run."
        )
        return 1

    user_repo_root = get_user_repo_root_from_git(repo_path)
    br_pre_commit_repo_root = get_br_pre_commit_root_from_git()
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

    if not dry_run:
        for msg in merge_project_config(user_repo_root, br_pre_commit_repo_root):
            print(msg)
        for msg in merge_project_pyproject(user_repo_root, br_pre_commit_repo_root):
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
    parser.add_argument("repo_path", nargs="?", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return install(args.repo_path, args.force, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
