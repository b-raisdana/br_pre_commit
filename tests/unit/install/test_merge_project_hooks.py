"""Regression tests for installing shared hooks into consuming projects."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TypedDict, cast

import pytest
import yaml

from src import install
from src.helper import project_config, project_hooks

pytestmark = pytest.mark.unit


class HookDefinition(TypedDict, total=False):
    id: str
    name: str
    entry: str
    stages: list[str]


class RepoDefinition(TypedDict, total=False):
    repo: str
    hooks: list[HookDefinition]


class ConfigDefinition(TypedDict, total=False):
    repos: list[RepoDefinition]


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    consumer_root = tmp_path / "consumer"
    consumer_root.mkdir()
    config_path = consumer_root / ".pre-commit-config.yaml"
    config_path.write_text("repos: []\n", encoding="utf-8")
    tool_root = Path(install.__file__).resolve().parents[1]
    monkeypatch.setattr(project_hooks, "get_pre_commit_config_yaml_path", lambda: config_path)
    monkeypatch.setattr(project_config, "get_pyproject_toml_path", lambda: consumer_root / "pyproject.toml")
    return consumer_root, tool_root, config_path


def _hook_map(config: ConfigDefinition) -> dict[str, HookDefinition]:
    repos = config.get("repos", [])
    return {
        hook_id: hook
        for repo in repos
        for hook in repo.get("hooks", [])
        if isinstance((hook_id := hook.get("id")), str)
    }


def test_installer_adds_complete_shared_hook_set_and_is_idempotent(roots: tuple[Path, Path, Path]) -> None:
    consumer_root, tool_root, config_path = roots
    tests_root = consumer_root / "tests"
    tests_root.mkdir()
    (tests_root / "test_sample.py").write_text("def test_sample() -> None: pass\n", encoding="utf-8")

    project_config.merge_project_pyproject_config(consumer_root, tool_root)
    install.merge_project_config(consumer_root, tool_root)
    installed = cast(ConfigDefinition, yaml.safe_load(config_path.read_text(encoding="utf-8")))
    template = cast(
        ConfigDefinition,
        yaml.safe_load((tool_root / ".pre-commit-config.yaml").read_text(encoding="utf-8")),
    )
    expected_ids = {
        hook_id for repo in template["repos"] for hook in repo["hooks"] if isinstance((hook_id := hook.get("id")), str)
    }
    hooks = _hook_map(installed)

    assert set(hooks) == expected_ids
    assert hooks["pytest-fast"]["entry"] == "python -m pytest -q --import-mode=importlib -m unit tests"
    assert hooks["pytest-fast"]["stages"] == ["pre-commit"]
    assert hooks["incremental-ratchet"]["entry"] == "python -m br_pre_commit.src.ratchet"
    assert hooks["no-object-annotations"]["entry"] == "python -m br_pre_commit.src.check_no_object_annotations"

    project_data = tomllib.loads((consumer_root / "pyproject.toml").read_text(encoding="utf-8"))
    wrapper = project_data["tool"]["br_pre_commit"]["wrapper"]
    assert "pytest-fast" in wrapper["read-only-hooks"]
    assert "incremental-ratchet" in wrapper["mutating-hooks"]

    before = config_path.read_bytes()
    assert install.merge_project_config(consumer_root, tool_root) == []
    assert config_path.read_bytes() == before
    project_before = (consumer_root / "pyproject.toml").read_bytes()
    assert project_config.merge_project_pyproject_config(consumer_root, tool_root) == []
    assert (consumer_root / "pyproject.toml").read_bytes() == project_before


def test_installer_skips_pytest_when_consumer_has_no_python_test_suite(
    roots: tuple[Path, Path, Path],
) -> None:
    consumer_root, tool_root, config_path = roots

    install.merge_project_config(consumer_root, tool_root)
    installed = cast(ConfigDefinition, yaml.safe_load(config_path.read_text(encoding="utf-8")))
    hooks = _hook_map(installed)

    assert "pytest-fast" not in hooks
    assert "no-commit-to-trunk" in hooks


def test_installer_creates_missing_pre_commit_config(roots: tuple[Path, Path, Path]) -> None:
    consumer_root, tool_root, config_path = roots
    config_path.unlink()

    messages = install.merge_project_config(consumer_root, tool_root)

    assert config_path.is_file()
    assert any(message.startswith("Created ") for message in messages)
    installed = cast(ConfigDefinition, yaml.safe_load(config_path.read_text(encoding="utf-8")))
    assert "incremental-ratchet" in _hook_map(installed)


def test_self_hosted_install_keeps_src_module_entry(roots: tuple[Path, Path, Path]) -> None:
    _, tool_root, _ = roots

    hook = project_hooks._consumer_hook(
        {"id": "incremental-ratchet", "entry": "python -m src.ratchet"},
        tool_root,
        tool_root,
    )

    assert hook["entry"] == "python -m src.ratchet"


def test_installer_wires_a_fresh_consumer_checkout(
    roots: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumer_root, tool_root, config_path = roots
    tests_root = consumer_root / "tests"
    tests_root.mkdir()
    (tests_root / "test_sample.py").write_text("def test_sample() -> None: pass\n", encoding="utf-8")
    git_hooks = consumer_root / ".git" / "hooks"
    git_hooks.mkdir(parents=True)
    monkeypatch.setattr(install, "verify_requirements", lambda: [])
    monkeypatch.setattr(install, "get_user_repo_root_from_git", lambda _cwd: consumer_root)
    monkeypatch.setattr(install, "get_br_pre_commit_root_from_git", lambda: tool_root)
    monkeypatch.setattr(install, "get_git_dir", lambda _root: git_hooks.parent)
    monkeypatch.setattr(install, "_generate_hook_content", lambda _user, _tool: "#!/bin/sh\nexit 0\n")
    monkeypatch.delenv("USER_REPO_ROOT", raising=False)
    monkeypatch.delenv("BR_PRE_COMMIT_REPO_ROOT", raising=False)

    assert install.install(consumer_root, force=True, dry_run=False) == 0

    hook_path = git_hooks / "pre-commit"
    assert hook_path.read_text(encoding="utf-8") == "#!/bin/sh\nexit 0\n"
    config = cast(ConfigDefinition, yaml.safe_load(config_path.read_text(encoding="utf-8")))
    assert "pytest-fast" in _hook_map(config)
    project = tomllib.loads((consumer_root / "pyproject.toml").read_text(encoding="utf-8"))
    assert "pytest-fast" in project["tool"]["br_pre_commit"]["wrapper"]["read-only-hooks"]


def test_installer_completes_existing_hooks_and_preserves_project_entries(
    roots: tuple[Path, Path, Path],
) -> None:
    consumer_root, tool_root, config_path = roots
    config_path.write_text(
        "repos:\n"
        "- repo: local\n"
        "  hooks:\n"
        "  - id: incremental-ratchet\n"
        "    stages: [pre-commit]\n"
        "  - id: project-custom-check\n"
        "    name: keep this custom hook\n"
        "    language: system\n"
        "    entry: python custom_check.py\n"
        "    stages: [pre-commit]\n",
        encoding="utf-8",
    )

    install.merge_project_config(consumer_root, tool_root)
    installed = cast(ConfigDefinition, yaml.safe_load(config_path.read_text(encoding="utf-8")))
    hooks = _hook_map(installed)
    template = cast(
        ConfigDefinition,
        yaml.safe_load((tool_root / ".pre-commit-config.yaml").read_text(encoding="utf-8")),
    )
    template_hooks = _hook_map(template)

    assert hooks["incremental-ratchet"]["name"] == template_hooks["incremental-ratchet"]["name"]
    assert hooks["incremental-ratchet"]["entry"] == "python -m br_pre_commit.src.ratchet"
    assert hooks["incremental-ratchet"]["stages"] == ["pre-commit"]
    assert hooks["project-custom-check"]["entry"] == "python custom_check.py"


def test_installer_merges_shared_classifications_without_dropping_custom_ids(
    roots: tuple[Path, Path, Path],
) -> None:
    consumer_root, tool_root, _ = roots
    pyproject_path = consumer_root / "pyproject.toml"
    pyproject_path.write_text(
        "[tool.br_pre_commit.wrapper]\n"
        'read-only-hooks = ["project-reader"]\n'
        'mutating-hooks = ["project-mutator"]\n'
        'unknown-hook-policy = "error"\n',
        encoding="utf-8",
    )

    project_config.merge_project_pyproject_config(consumer_root, tool_root)
    installed = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    wrapper = installed["tool"]["br_pre_commit"]["wrapper"]
    source = tomllib.loads((tool_root / "pyproject.toml").read_text(encoding="utf-8"))
    source_wrapper = source["tool"]["br_pre_commit"]["wrapper"]

    assert set(source_wrapper["read-only-hooks"]).issubset(wrapper["read-only-hooks"])
    assert set(source_wrapper["mutating-hooks"]).issubset(wrapper["mutating-hooks"])
    assert "project-reader" in wrapper["read-only-hooks"]
    assert "project-mutator" in wrapper["mutating-hooks"]
    assert wrapper["unknown-hook-policy"] == "error"

    before = pyproject_path.read_bytes()
    assert project_config.merge_project_pyproject_config(consumer_root, tool_root) == []
    assert pyproject_path.read_bytes() == before
