import importlib.util
from pathlib import Path

import pytest

# The hook file is named with hyphens (sync-skill-files.py), so it can't be
# imported by module name; load it by path instead.
_hook_path = Path(__file__).resolve().parents[1] / "src/br_pre_commit/sync_skill_files.py"
_spec = importlib.util.spec_from_file_location("sync_skill_files", _hook_path)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

pytestmark = pytest.mark.unit

AGENTS = m.AGENTS


def _entry(slot, status, blob=b"v"):
    return (slot, status, blob)


# ---- parse_staged_name_status (the git-detection source of truth) ----


def test_parse_staged_name_status_classifies_add_modify_delete():
    raw = "\n".join(
        [
            "M\t.claude/skills/pytest/SKILL.md",
            "A\t.codex/skills/new-skill/SKILL.md",
            "D\t.kilo/skills/old-skill/SKILL.md",
            "M\tapp/foo.py",
        ]
    )
    entries = m.parse_staged_name_status(raw)
    by_path = dict(entries)
    assert by_path[".claude/skills/pytest/SKILL.md"] == "M"
    assert by_path[".codex/skills/new-skill/SKILL.md"] == "A"
    assert by_path[".kilo/skills/old-skill/SKILL.md"] == "D"
    # non-skill paths still parse (classifier decides relevance later)
    assert by_path["app/foo.py"] == "M"


def test_parse_staged_name_status_rename_uses_new_path():
    raw = "R100\told/.claude/skills/a/SKILL.md\t.claude/skills/b/SKILL.md"
    entries = m.parse_staged_name_status(raw)
    assert entries == [(".claude/skills/b/SKILL.md", "R")]


def test_parse_staged_name_status_ignores_untracked_and_unknown_codes():
    raw = "\n".join(["??\treadme.md", "X\tsome/file"])
    assert m.parse_staged_name_status(raw) == []


def test_parse_staged_name_status_empty_input():
    assert m.parse_staged_name_status("") == []


# ---- classify_skill_path ----


def test_classify_agent_skill_path():
    assert m.classify_skill_path(".claude/skills/pytest/SKILL.md") == ("pytest", "claude")
    assert m.classify_skill_path(".kilo/skills/git-commit/SKILL.md") == ("git-commit", "kilo")


def test_classify_github_git_commit_special():
    assert m.classify_skill_path(".github/git-commit/SKILL.md") == ("git-commit", m._GITHUB_PATH)


def test_classify_rejects_non_skill_paths():
    assert m.classify_skill_path(".claude/skills/pytest/README.md") is None
    assert m.classify_skill_path("app/foo.py") is None
    assert m.classify_skill_path(".github/workflows/ci.yml") is None
    assert m.classify_skill_path(".foo/skills/bar/SKILL.md") is None  # ".foo" not an agent


# ---- is_excluded ----


def test_is_excluded_by_hardcoded_and_prefix():
    assert m.is_excluded("use-aget-skills")
    assert m.is_excluded("kilo-only-todo-discipline")
    assert m.is_excluded("claude-only-review")
    assert m.is_excluded("codex-only-experimental")


def test_is_not_excluded_for_shared_skills():
    assert not m.is_excluded("pytest")
    assert not m.is_excluded("optimization-review")


# ---- mirror_slots ----


def test_mirror_slots_includes_github_only_for_git_commit(tmp_path):
    parents = {a: tmp_path / f".{a}/skills" for a in AGENTS}
    shared = m.mirror_slots(tmp_path, parents, "pytest")
    assert {slot for slot, _ in shared} == set(AGENTS)
    special = m.mirror_slots(tmp_path, parents, "git-commit")
    assert {slot for slot, _ in special} == set(AGENTS) | {m._GITHUB_PATH}
    gh = [p for slot, p in special if slot == m._GITHUB_PATH][0]
    assert gh == tmp_path / ".github" / "git-commit" / "SKILL.md"


# ---- compute_intent (staged -> safe plan) ----


def test_intent_single_canonical_modification():
    changes = {"pytest": [_entry("claude", "modify", b"v2")]}
    mods, deletions, conflicts = m.compute_intent(changes)
    assert mods == {"pytest": b"v2"}
    assert deletions == set() and conflicts == set()


def test_intent_same_version_across_agents_is_not_a_conflict():
    changes = {
        "pytest": [
            _entry("claude", "modify", b"v2"),
            _entry("codex", "modify", b"v2"),
        ]
    }
    mods, deletions, conflicts = m.compute_intent(changes)
    assert mods == {"pytest": b"v2"}
    assert conflicts == set()


def test_intent_multiple_distinct_staged_versions_is_a_conflict():
    changes = {
        "pytest": [
            _entry("claude", "modify", b"A"),
            _entry("codex", "modify", b"B"),
        ]
    }
    mods, deletions, conflicts = m.compute_intent(changes)
    assert conflicts == {"pytest"}
    assert mods == {} and deletions == set()


def test_intent_staged_delete_only():
    changes = {"pytest": [("claude", "delete", None)]}
    mods, deletions, conflicts = m.compute_intent(changes)
    assert deletions == {"pytest"}
    assert mods == {} and conflicts == set()


def test_intent_modify_and_delete_same_skill_is_a_conflict():
    changes = {"pytest": [_entry("claude", "modify", b"A"), ("codex", "delete", None)]}
    mods, deletions, conflicts = m.compute_intent(changes)
    assert conflicts == {"pytest"}
    assert deletions == {"pytest"}
    assert mods == {}
