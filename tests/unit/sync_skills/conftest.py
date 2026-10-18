import pytest

import src.sync_skills.core as core


@pytest.fixture(autouse=True)
def configured_test_skill_slots(monkeypatch):
    monkeypatch.setattr(core, "AGENTS", ["claude", "agents", "devin", "copilot", "kiro", "kilo"])
    monkeypatch.setattr(core.sync_skills_config, "github_git_commit", True)
