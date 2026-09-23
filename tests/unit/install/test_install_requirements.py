"""Tests for the br_pre_commit installer's environment checks."""

from __future__ import annotations

import importlib.util
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest import mock

import pytest
import yaml

INSTALL_MODULE = "br_pre_commit.install.install"
INSTALL_DIR = Path(__file__).resolve().parents[3] / "install"
pytestmark = pytest.mark.unit


def _load_install_module():
    """Import install.py by path so the test does not depend on PYTHONPATH."""
    spec = importlib.util.spec_from_file_location(INSTALL_MODULE, INSTALL_DIR / "install.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[INSTALL_MODULE] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def install():
    return _load_install_module()


def test_installer_import_does_not_require_runtime_repository_environment(monkeypatch):
    monkeypatch.delenv("BR_PRE_COMMIT_REPO_ROOT", raising=False)
    monkeypatch.delenv("USER_REPO_ROOT", raising=False)

    assert _load_install_module() is not None


def test_generated_posix_hook_exports_both_repository_roots(install, monkeypatch, tmp_path):
    user_repo_root = tmp_path / "consumer"
    tool_repo_root = tmp_path / "br_pre_commit"
    monkeypatch.setattr(install, "get_active_venv", lambda: tmp_path / "venv" / "bin" / "python")

    hook = install.generate_posix_hook(user_repo_root, tool_repo_root)

    assert f"export BR_PRE_COMMIT_REPO_ROOT={tool_repo_root}" in hook
    assert f"export USER_REPO_ROOT={user_repo_root}" in hook


def test_generated_posix_hook_quotes_paths(install, monkeypatch, tmp_path):
    user_repo_root = tmp_path / "consumer's project"
    tool_repo_root = tmp_path / "shared tool"
    monkeypatch.setattr(install, "get_active_venv", lambda: tmp_path / "virtual env" / "bin" / "python")

    hook = install.generate_posix_hook(user_repo_root, tool_repo_root)

    assert "export USER_REPO_ROOT=" in hook
    assert f"export USER_REPO_ROOT={shlex.quote(str(user_repo_root))}" in hook
    assert f"export BR_PRE_COMMIT_REPO_ROOT={shlex.quote(str(tool_repo_root))}" in hook


def test_generated_powershell_hook_quotes_repository_paths(install, monkeypatch, tmp_path):
    user_repo_root = tmp_path / "consumer's project"
    tool_repo_root = tmp_path / "shared tool"
    monkeypatch.setattr(install, "get_active_venv", lambda: tmp_path / "virtual env" / "python.exe")

    hook = install.generate_powershell_hook(user_repo_root, tool_repo_root)

    assert f"export USER_REPO_ROOT={shlex.quote(str(user_repo_root))}" in hook
    assert f"export BR_PRE_COMMIT_REPO_ROOT={shlex.quote(str(tool_repo_root))}" in hook


def test_merge_project_config_repairs_shared_entries_and_preserves_project_settings(install, tmp_path):
    user_repo_root = tmp_path / "consumer"
    user_repo_root.mkdir()
    config_path = user_repo_root / ".pre-commit-config.yaml"
    config_path.write_text(
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: incremental-ratchet\n"
        "        name: project ratchet\n"
        "        entry: br_pre_commit/ratchet\n"
        "        language: system\n"
        "        files: ^app/.*\\.py$\n"
        "        stages: [manual]\n"
        "      - id: sync-skill-files\n"
        "        name: project sync\n"
        "        entry: python br_pre_commit/src/br_pre_commit/sync_skill_files.py\n"
        "        language: system\n"
        "        files: ^project-skills/\n",
        encoding="utf-8",
    )

    messages = install.merge_project_config(user_repo_root, INSTALL_DIR.parent)
    merged = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    hooks = {hook["id"]: hook for repo in merged["repos"] for hook in repo["hooks"]}

    assert hooks["incremental-ratchet"]["entry"] == "python -m ratchet"
    assert hooks["incremental-ratchet"]["files"] == r"^app/.*\.py$"
    assert hooks["incremental-ratchet"]["stages"] == ["manual"]
    assert hooks["sync-skill-files"]["entry"] == "python -m sync_skills"
    assert hooks["sync-skill-files"]["files"] == "^project-skills/"
    assert hooks["sync-skill-files"]["stages"] == ["pre-commit"]
    assert "Updated shared module entry for 'incremental-ratchet'" in messages


def test_merge_project_config_installs_complete_master_config(install, tmp_path):
    user_repo_root = tmp_path / "consumer"
    user_repo_root.mkdir()

    install.merge_project_config(user_repo_root, INSTALL_DIR.parent)

    merged = yaml.safe_load((user_repo_root / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    master = yaml.safe_load((INSTALL_DIR.parent / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    merged_ids = {hook["id"] for repo in merged["repos"] for hook in repo["hooks"]}
    master_ids = {hook["id"] for repo in master["repos"] for hook in repo["hooks"]}
    assert merged_ids == master_ids
    assert all("stages" in hook for repo in merged["repos"] for hook in repo["hooks"])


def test_merge_project_config_rejects_invalid_yaml_structure_without_overwriting(install, tmp_path):
    user_repo_root = tmp_path / "consumer"
    user_repo_root.mkdir()
    config_path = user_repo_root / ".pre-commit-config.yaml"
    original = "repos: invalid\n"
    config_path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="top-level 'repos' list"):
        install.merge_project_config(user_repo_root, INSTALL_DIR.parent)

    assert config_path.read_text(encoding="utf-8") == original


def test_merge_project_pyproject_adds_defaults_and_selects_existing_app_tree(install, tmp_path):
    user_repo_root = tmp_path / "consumer"
    (user_repo_root / "app").mkdir(parents=True)
    pyproject_path = user_repo_root / "pyproject.toml"
    pyproject_path.write_text("[project]\nname = 'consumer'\n", encoding="utf-8")

    messages = install.merge_project_pyproject(user_repo_root, INSTALL_DIR.parent)
    with pyproject_path.open("rb") as pyproject_file:
        merged = tomllib.load(pyproject_file)
    settings = merged["tool"]["br_pre_commit"]

    assert settings["ratchet"]["target"] == "app"
    assert settings["wrapper"]["unknown-hook-policy"] == "error"
    assert "full_backup_exclude_dir_regex" in settings["backup"]
    assert len(messages) == 3


def test_merge_project_pyproject_preserves_existing_section(install, tmp_path):
    user_repo_root = tmp_path / "consumer"
    user_repo_root.mkdir()
    pyproject_path = user_repo_root / "pyproject.toml"
    pyproject_path.write_text(
        "[tool.br_pre_commit.ratchet]\ntarget = 'package'\nmax-lines = 123\n",
        encoding="utf-8",
    )

    install.merge_project_pyproject(user_repo_root, INSTALL_DIR.parent)
    with pyproject_path.open("rb") as pyproject_file:
        merged = tomllib.load(pyproject_file)

    assert merged["tool"]["br_pre_commit"]["ratchet"] == {"target": "package", "max-lines": 123}


def test_install_writes_executable_hook_and_complete_config(install, monkeypatch, tmp_path):
    user_repo_root = tmp_path / "consumer"
    user_repo_root.mkdir()
    subprocess.run(["git", "init", "-q", str(user_repo_root)], check=True)
    monkeypatch.setattr(install, "verify_requirements", lambda: [])
    monkeypatch.setattr(install, "get_active_venv", lambda: tmp_path / "venv" / "bin" / "python")
    monkeypatch.setattr(install, "get_br_pre_commit_root_from_git", lambda: INSTALL_DIR.parent)

    result = install.install(str(user_repo_root), force=False, dry_run=False)

    hook_path = user_repo_root / ".git" / "hooks" / "pre-commit"
    hook = hook_path.read_text(encoding="utf-8")
    config = yaml.safe_load((user_repo_root / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    with (user_repo_root / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    hooks = {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}
    assert result == 0
    assert hook_path.stat().st_mode & 0o111
    assert f"export USER_REPO_ROOT={user_repo_root}" in hook
    assert hooks["incremental-ratchet"]["entry"] == "python -m ratchet"
    assert hooks["check-pandera-decorator"]["entry"] == "python -m check_pandera_decorator"
    assert hooks["sync-skill-files"]["entry"] == "python -m sync_skills"
    assert hooks["no-commit-to-main"]["entry"] == "python -m check_no_commit_to_main"
    assert pyproject["tool"]["br_pre_commit"]["ratchet"]["target"] == "src"


def test_install_dry_run_does_not_write_hook_or_config(install, monkeypatch, tmp_path):
    user_repo_root = tmp_path / "consumer"
    user_repo_root.mkdir()
    subprocess.run(["git", "init", "-q", str(user_repo_root)], check=True)
    monkeypatch.setattr(install, "verify_requirements", lambda: [])
    monkeypatch.setattr(install, "get_active_venv", lambda: tmp_path / "venv" / "bin" / "python")
    monkeypatch.setattr(install, "get_br_pre_commit_root_from_git", lambda: INSTALL_DIR.parent)

    result = install.install(str(user_repo_root), force=False, dry_run=True)

    assert result == 0
    assert not (user_repo_root / ".git" / "hooks" / "pre-commit").exists()
    assert not (user_repo_root / ".pre-commit-config.yaml").exists()
    assert not (user_repo_root / "pyproject.toml").exists()


def test_required_packages_mirror_requirements_txt(install):
    """REQUIRED_PACKAGES must match the import names implied by requirements.txt."""
    expected = {
        "yaml",  # pyyaml
        "pre_commit",  # pre-commit
        "radon",
        "ruff",
        "mypy",
        "pytest",
        "pydantic_settings",  # pydantic-settings
    }
    assert set(install.REQUIRED_PACKAGES) == expected


def test_verify_requirements_empty_when_all_present(install):
    """When every required package is importable, verify_requirements returns []."""
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name in install.REQUIRED_PACKAGES:
            return mock.MagicMock()
        return real_find_spec(name, *args, **kwargs)

    with mock.patch.object(importlib.util, "find_spec", side_effect=fake_find_spec):
        assert install.verify_requirements() == []


def test_verify_requirements_reports_missing(install):
    """verify_requirements includes the import names that are not importable."""
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name in {"yaml", "radon"}:
            return None
        return real_find_spec(name, *args, **kwargs)

    with mock.patch.object(importlib.util, "find_spec", side_effect=fake_find_spec):
        missing = install.verify_requirements()

    # yaml and radon are reported missing; everything else is whatever the real
    # environment has (the test does not assert a clean environment).
    assert "yaml" in missing
    assert "radon" in missing
    assert set(missing).issubset(set(install.REQUIRED_PACKAGES))


# def test_install_aborts_on_missing_requirements(install, capsys):
#     """install() returns 1 and prints an error when packages are missing."""
#     with mock.patch.object(install, "verify_requirements", return_value=["yaml", "radon"]), \
#          mock.patch.object(install, "get_user_repo_root", side_effect=AssertionError("should not reach git")):
#         result = install.install(None, force=False, dry_run=False)
#
#     assert result == 1
#     captured = capsys.readouterr()
#     assert "yaml" in captured.out and "radon" in captured.out


# def test_install_skips_git_lookup_in_dry_run_when_requirements_missing(install, capsys):
#     """Even --dry-run must not proceed when the environment is incomplete."""
#     with mock.patch.object(install, "verify_requirements", return_value=["radon"]), \
#          mock.patch.object(install, "get_user_repo_root", side_effect=AssertionError("should not reach git")):
#         result = install.install(None, force=False, dry_run=True)
#
#     assert result == 1
