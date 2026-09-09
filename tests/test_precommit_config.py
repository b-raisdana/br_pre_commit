import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/br_pre_commit"))
import precommit_config  # noqa: E402

pytestmark = pytest.mark.unit


def test_repository_pre_commit_config_uses_registered_hooks():
    repo_root = Path(__file__).resolve().parents[1]
    hook_ids = precommit_config.enabled_pre_commit_hook_ids(repo_root / ".pre-commit-config.yaml")

    specs, unknown = precommit_config.classify_hooks(hook_ids, policy="error")

    assert unknown == []
    assert [spec.hook_id for spec in specs] == hook_ids


def test_enabled_hooks_reads_only_pre_commit_stage(tmp_path):
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: pytest-fast\n"
        "      - id: push-only\n"
        "        stages: [pre-push]\n"
        "      - id: check-yaml\n"
        "        stages: [pre-commit]\n"
    )

    assert precommit_config.enabled_pre_commit_hook_ids(config) == ["pytest-fast", "check-yaml"]


def test_unknown_hook_error_policy_fails():
    with pytest.raises(ValueError, match="unregistered pre-commit hook"):
        precommit_config.classify_hooks(["pytest-fast", "new-hook"], policy="error")


def test_unknown_hook_warn_policy_reports_and_serializes():
    specs, unknown = precommit_config.classify_hooks(["pytest-fast", "new-hook"], policy="warn")

    assert unknown == ["new-hook"]
    assert [(spec.hook_id, spec.mutates_files) for spec in specs] == [("pytest-fast", False), ("new-hook", True)]


def test_ratchet_hook_is_registered_without_recursion():
    specs, unknown = precommit_config.classify_hooks([precommit_config.RATCHET_HOOK_ID], policy="error")

    assert unknown == []
    assert specs == [precommit_config.HookSpec(precommit_config.RATCHET_HOOK_ID, mutates_files=False)]


def test_project_settings_override_shared_defaults(tmp_path):
    (tmp_path / ".br-pre-commit.toml").write_text('[wrapper]\nunknown-hook-policy = "warn"\njob-timeout-seconds = 42\n')

    assert precommit_config.unknown_hook_policy(tmp_path) == "warn"
    assert precommit_config.job_timeout_seconds(tmp_path) == 42
