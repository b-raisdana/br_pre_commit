from pathlib import Path

import pytest
import yaml

from src.precommit_wrapper import config, hooks

pytestmark = pytest.mark.unit


def test_repository_pre_commit_config_uses_registered_hooks():
    br_pre_commit_repo_root = Path(__file__).resolve().parents[3]
    hook_ids = hooks.enabled_pre_commit_hook_ids(br_pre_commit_repo_root / ".pre-commit-config.yaml")

    specs, unknown = config.classify_hooks(hook_ids, policy="error")

    assert unknown == []
    assert [spec.hook_id for spec in specs] == hook_ids


def test_repository_config_has_one_master_switch_for_every_recognized_hook():
    br_pre_commit_repo_root = Path(__file__).resolve().parents[3]
    config_data = yaml.safe_load((br_pre_commit_repo_root / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks_in_config = [hook for repo in config_data["repos"] for hook in repo["hooks"]]
    hook_ids = [hook["id"] for hook in hooks_in_config]
    recognized = config.get_mutating_hooks() | config.wrapper_config.read_only_hooks

    assert len(hook_ids) == len(set(hook_ids))
    assert set(hook_ids) == recognized
    # An omitted ``stages`` key means enabled (see enabled_pre_commit_hook_ids); when present
    # it must be pre-commit, so no recognized hook is switched off for normal commits.
    assert all(hook.get("stages", ["pre-commit"]) == ["pre-commit"] for hook in hooks_in_config)


def test_enabled_hooks_reads_only_pre_commit_stage(tmp_path):
    cfg_file = tmp_path / ".pre-commit-config.yaml"
    cfg_file.write_text(
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: pytest-fast\n"
        "      - id: push-only\n"
        "        stages: [pre-push]\n"
        "      - id: check-yaml\n"
        "        stages: [pre-commit]\n"
    )

    assert hooks.enabled_pre_commit_hook_ids(cfg_file) == ["pytest-fast", "check-yaml"]


def test_hook_master_switch_can_disable_and_enable_hook(tmp_path):
    cfg_file = tmp_path / ".pre-commit-config.yaml"
    cfg_file.write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: no-commit-to-trunk\n        stages: [manual]\n",
        encoding="utf-8",
    )

    assert not hooks.pre_commit_hook_is_enabled("no-commit-to-trunk", cfg_file)

    cfg_file.write_text(cfg_file.read_text(encoding="utf-8").replace("manual", "pre-commit"), encoding="utf-8")

    assert hooks.pre_commit_hook_is_enabled("no-commit-to-trunk", cfg_file)


def test_unknown_hook_error_policy_fails():
    with pytest.raises(ValueError, match="unregistered pre-commit hook"):
        config.classify_hooks(["pytest-fast", "new-hook"], policy="error")


def test_read_only_hooks_loaded_from_project_toml(tmp_path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.br_pre_commit.wrapper]\nread-only-hooks = ["custom-check", "ruff-format"]\n'
        'mutating-hooks = ["ruff-format"]\n',
        encoding="utf-8",
    )
    settings = config.WrapperConfig.from_pyproject_toml("wrapper", pyproject)
    monkeypatch.setattr(config, "wrapper_config", settings)

    specs, unknown = config.classify_hooks(["custom-check", "ruff-format"], policy="error")

    assert unknown == []
    assert specs == [config.HookSpec("custom-check", False), config.HookSpec("ruff-format", True)]
    with pytest.raises(ValueError, match="unregistered pre-commit hook.*check-yaml"):
        config.classify_hooks(["check-yaml"], policy="error")


@pytest.mark.parametrize("contents", ["", "[tool.br_pre_commit.wrapper]\nread-only-hooks = []\n"])
def test_missing_or_empty_read_only_hooks_keeps_unknown_hooks_serial(tmp_path, monkeypatch, contents):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(contents, encoding="utf-8")
    settings = config.WrapperConfig.from_pyproject_toml("wrapper", pyproject)
    monkeypatch.setattr(config, "wrapper_config", settings)

    specs, unknown = config.classify_hooks(["check-yaml"], policy="warn")

    assert settings.read_only_hooks == frozenset()
    assert unknown == ["check-yaml"]
    assert specs == [config.HookSpec("check-yaml", True)]


def test_mutating_hooks_loaded_from_project_toml(tmp_path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.br_pre_commit.wrapper]\nmutating-hooks = ["custom-fixer", "renamed-ratchet"]\n', encoding="utf-8"
    )
    settings = config.WrapperConfig.from_pyproject_toml("wrapper", pyproject)
    monkeypatch.setattr(config, "wrapper_config", settings)

    specs, unknown = config.classify_hooks(["custom-fixer", "renamed-ratchet"], policy="error")

    assert unknown == []
    assert config.get_mutating_hooks() == frozenset({"custom-fixer", "renamed-ratchet"})
    assert specs == [config.HookSpec("custom-fixer", True), config.HookSpec("renamed-ratchet", True)]
    with pytest.raises(ValueError, match="unregistered pre-commit hook.*ruff-format"):
        config.classify_hooks(["ruff-format"], policy="error")


@pytest.mark.parametrize("contents", ["", "[tool.br_pre_commit.wrapper]\nmutating-hooks = []\n"])
def test_missing_or_empty_mutating_hooks_uses_unknown_policy(tmp_path, monkeypatch, contents):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(contents, encoding="utf-8")
    settings = config.WrapperConfig.from_pyproject_toml("wrapper", pyproject)
    monkeypatch.setattr(config, "wrapper_config", settings)

    assert config.get_mutating_hooks() == frozenset()
    specs, unknown = config.classify_hooks(["ruff-format"], policy="warn")
    assert unknown == ["ruff-format"]
    assert specs == [config.HookSpec("ruff-format", True)]
    with pytest.raises(ValueError, match="unregistered pre-commit hook.*ruff-format"):
        config.classify_hooks(["ruff-format"], policy="error")


def test_unknown_hook_warn_policy_reports_and_serializes():
    specs, unknown = config.classify_hooks(["pytest-fast", "new-hook"], policy="warn")

    assert unknown == ["new-hook"]
    assert [(spec.hook_id, spec.mutates_files) for spec in specs] == [("pytest-fast", False), ("new-hook", True)]


def test_ratchet_hook_is_registered_without_recursion():
    from src.config import br_pre_commit_config

    hook_id = br_pre_commit_config.ratchet_hook_id
    specs, unknown = config.classify_hooks([hook_id], policy="error")

    assert unknown == []
    assert specs == [config.HookSpec(hook_id, mutates_files=True)]


def test_default_trunk_regex_matches_main_develop_uat():
    assert config.wrapper_config.protected_branches_regex == "^(main|develop|uat)$"


@pytest.mark.parametrize("value", ['["main", ""]', "[1]", "123"])
def test_protected_branches_regex_rejects_invalid_values(tmp_path, value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="protected-branches-regex"):
        config.WrapperConfig.model_validate({"protected-branches-regex": eval(value)})


@pytest.mark.parametrize("value", ["(", "*", "[a-"])
def test_protected_branches_regex_rejects_invalid_regex(tmp_path, value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="protected-branches-regex"):
        config.WrapperConfig.model_validate({"protected-branches-regex": value})
