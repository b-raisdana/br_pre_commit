import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import precommit_wrapper.config as config
import precommit_wrapper.hooks as hooks
from config import br_pre_commit_config  # noqa: E402

pytestmark = pytest.mark.unit


def test_repository_pre_commit_config_uses_registered_hooks():
    repo_root = Path(__file__).resolve().parents[3]
    hook_ids = hooks.enabled_pre_commit_hook_ids(repo_root / ".pre-commit-config.yaml")

    specs, unknown = config.classify_hooks(hook_ids, policy="error")

    assert unknown == []
    assert [spec.hook_id for spec in specs] == hook_ids


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


def test_unknown_hook_error_policy_fails():
    with pytest.raises(ValueError, match="unregistered pre-commit hook"):
        config.classify_hooks(["pytest-fast", "new-hook"], policy="error")


def test_unknown_hook_warn_policy_reports_and_serializes():
    specs, unknown = config.classify_hooks(["pytest-fast", "new-hook"], policy="warn")

    assert unknown == ["new-hook"]
    assert [(spec.hook_id, spec.mutates_files) for spec in specs] == [("pytest-fast", False), ("new-hook", True)]


def test_ratchet_hook_is_registered_without_recursion():
    hook_id = br_pre_commit_config.ratchet_hook_id
    specs, unknown = config.classify_hooks([hook_id], policy="error")

    assert unknown == []
    assert specs == [config.HookSpec(hook_id, mutates_files=False)]


def test_main_is_protected_by_default(tmp_path):
    assert config.wrapper_config.protected_branches == ["main"]


@pytest.mark.parametrize("value", ['"main"', '["main", ""]', "[1]"])
def test_protected_branches_rejects_invalid_values(tmp_path, value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="protected-branches"):
        config.WrapperConfig.model_validate({"protected-branches": eval(value)})
