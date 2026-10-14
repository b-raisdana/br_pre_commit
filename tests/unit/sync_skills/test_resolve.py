from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

import src.sync_skills.__main__ as main_mod
from src.helper.paths import git_subprocess_env
from src.sync_skills.core import RESOLVE_COMMAND
from src.sync_skills.resolve import interactive_resolve

pytestmark = pytest.mark.unit


def _run(br_pre_commit_repo: Path, args: list[str]) -> None:
    subprocess.run(
        ["git", "-C", str(br_pre_commit_repo), *args],
        check=True,
        capture_output=True,
        env=git_subprocess_env(inherit_index=False),
    )


def _staged(br_pre_commit_repo: Path, rel: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(br_pre_commit_repo), "show", f":{rel}"],
        check=True,
        capture_output=True,
        env=git_subprocess_env(inherit_index=False),
    )
    return result.stdout


@pytest.fixture
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    br_pre_commit_repo = tmp_path
    monkeypatch.delenv("GIT_INDEX_FILE", raising=False)
    _run(br_pre_commit_repo, ["init", "-q"])
    _run(br_pre_commit_repo, ["config", "user.email", "test@example.com"])
    _run(br_pre_commit_repo, ["config", "user.name", "Test"])
    return br_pre_commit_repo


def _skill_file(br_pre_commit_repo: Path, agent: str, skill: str) -> Path:
    path = br_pre_commit_repo / f".{agent}" / "skills" / skill / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _stage_all(br_pre_commit_repo: Path) -> None:
    _run(br_pre_commit_repo, ["add", "-A"])


def _commit_all(br_pre_commit_repo: Path, message: str = "init") -> None:
    _stage_all(br_pre_commit_repo)
    _run(br_pre_commit_repo, ["commit", "-q", "-m", message])


def _ask_answering(*answers: str) -> Callable[[str], str]:
    iterator = iter(answers)

    def ask(prompt: str) -> str:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise AssertionError(f"unexpected prompt: {prompt}") from exc

    return ask


def test_git_subprocess_env_drops_hook_repository_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_DIR", ".git")
    monkeypatch.setenv("GIT_WORK_TREE", ".")
    monkeypatch.setenv("GIT_INDEX_FILE", ".git/index")
    monkeypatch.setenv("GIT_PREFIX", "")

    env = git_subprocess_env(inherit_index=False)

    assert not {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX"} & env.keys()


# ---- staged version conflict ----


def test_resolves_staged_version_conflict(git_repo: Path) -> None:
    br_pre_commit_repo = git_repo
    claude = _skill_file(br_pre_commit_repo, "claude", "foo")
    claude.write_bytes(b"version A")
    kilo = _skill_file(br_pre_commit_repo, "kilo", "foo")
    kilo.write_bytes(b"version B")
    _stage_all(br_pre_commit_repo)

    rc = interactive_resolve(br_pre_commit_repo, ask=_ask_answering("1"))

    assert rc == 0
    assert claude.read_bytes() == b"version A"
    assert kilo.read_bytes() == b"version A"
    assert _staged(br_pre_commit_repo, ".kilo/skills/foo/SKILL.md") == b"version A"


def test_invalid_choice_prompts_again(git_repo: Path) -> None:
    br_pre_commit_repo = git_repo
    claude = _skill_file(br_pre_commit_repo, "claude", "foo")
    claude.write_bytes(b"version A")
    kilo = _skill_file(br_pre_commit_repo, "kilo", "foo")
    kilo.write_bytes(b"version B")
    _stage_all(br_pre_commit_repo)

    rc = interactive_resolve(br_pre_commit_repo, ask=_ask_answering("9", "abc", "2"))

    assert rc == 0
    assert claude.read_bytes() == b"version B"
    assert kilo.read_bytes() == b"version B"


def test_skipped_conflict_is_reported(git_repo: Path) -> None:
    br_pre_commit_repo = git_repo
    claude = _skill_file(br_pre_commit_repo, "claude", "foo")
    claude.write_bytes(b"version A")
    kilo = _skill_file(br_pre_commit_repo, "kilo", "foo")
    kilo.write_bytes(b"version B")
    _stage_all(br_pre_commit_repo)

    rc = interactive_resolve(br_pre_commit_repo, ask=_ask_answering(""))

    assert rc == 1
    assert claude.read_bytes() == b"version A"
    assert kilo.read_bytes() == b"version B"


# ---- staged-modified + staged-deleted conflict ----


def test_modify_delete_conflict_deletes_everywhere(git_repo: Path) -> None:
    br_pre_commit_repo = git_repo
    claude = _skill_file(br_pre_commit_repo, "claude", "foo")
    claude.write_bytes(b"version A")
    kilo = _skill_file(br_pre_commit_repo, "kilo", "foo")
    kilo.write_bytes(b"version A")
    _commit_all(br_pre_commit_repo)
    claude.write_bytes(b"version A2")
    kilo.unlink()
    _stage_all(br_pre_commit_repo)

    rc = interactive_resolve(br_pre_commit_repo, ask=_ask_answering("delete"))

    assert rc == 0
    assert not claude.exists()
    assert not kilo.exists()


def test_modify_delete_conflict_keep_uses_single_staged_version(git_repo: Path) -> None:
    br_pre_commit_repo = git_repo
    claude = _skill_file(br_pre_commit_repo, "claude", "foo")
    claude.write_bytes(b"version A")
    kilo = _skill_file(br_pre_commit_repo, "kilo", "foo")
    kilo.write_bytes(b"version A")
    _commit_all(br_pre_commit_repo)
    claude.write_bytes(b"version A2")
    kilo.unlink()
    _stage_all(br_pre_commit_repo)

    rc = interactive_resolve(br_pre_commit_repo, ask=_ask_answering("keep"))

    assert rc == 0
    assert claude.read_bytes() == b"version A2"
    assert kilo.read_bytes() == b"version A2"
    assert _staged(br_pre_commit_repo, ".kilo/skills/foo/SKILL.md") == b"version A2"


# ---- committed (clean) worktree divergence ----


def test_resolves_committed_divergence(git_repo: Path) -> None:
    br_pre_commit_repo = git_repo
    claude = _skill_file(br_pre_commit_repo, "claude", "foo")
    claude.write_bytes(b"version A")
    kilo = _skill_file(br_pre_commit_repo, "kilo", "foo")
    kilo.write_bytes(b"version A")
    _commit_all(br_pre_commit_repo)
    claude.write_bytes(b"diverged A")
    kilo.write_bytes(b"diverged B")
    _run(br_pre_commit_repo, ["commit", "-q", "-a", "-m", "diverge"])

    rc = interactive_resolve(br_pre_commit_repo, ask=_ask_answering("2"))

    assert rc == 0
    assert claude.read_bytes() == b"diverged B"
    assert kilo.read_bytes() == b"diverged B"


# ---- exclusions ----


def test_excluded_skill_is_not_prompted(git_repo: Path) -> None:
    br_pre_commit_repo = git_repo
    claude = _skill_file(br_pre_commit_repo, "claude", "kilo-only-foo")
    claude.write_bytes(b"version A")
    kilo = _skill_file(br_pre_commit_repo, "kilo", "kilo-only-foo")
    kilo.write_bytes(b"version B")
    _stage_all(br_pre_commit_repo)

    def fail(prompt: str) -> str:
        raise AssertionError(f"unexpected prompt: {prompt}")

    rc = interactive_resolve(br_pre_commit_repo, ask=fail)

    assert rc == 0
    assert claude.read_bytes() == b"version A"
    assert kilo.read_bytes() == b"version B"


# ---- hook message points at the resolver ----


def test_conflict_reason_mentions_resolver_command() -> None:
    conflict = {"foo": [("claude", "modify", b"A"), ("kilo", "modify", b"B")]}
    assert RESOLVE_COMMAND in main_mod._conflict_reason("foo", conflict)

    both = {"foo": [("claude", "modify", b"A"), ("kilo", "delete", None)]}
    assert RESOLVE_COMMAND in main_mod._conflict_reason("foo", both)


# ---- repo-root env bootstrap (install.py-style) ----


def test_ensure_repo_root_env_vars_defaults_missing_ones(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.sync_skills.resolve as resolve_mod

    # The br_pre_commit root is discovered from this module's own
    # checkout location, not from the working directory.
    expected_br_pre_commit_repo_root = Path(resolve_mod.__file__).resolve().parents[2]

    monkeypatch.delenv("USER_REPO_ROOT", raising=False)
    monkeypatch.delenv("BR_PRE_COMMIT_REPO_ROOT", raising=False)
    monkeypatch.chdir(git_repo)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

    resolve_mod._ensure_repo_root_env_vars()

    assert os.environ["USER_REPO_ROOT"] == str(git_repo)
    assert os.environ["BR_PRE_COMMIT_REPO_ROOT"] == str(expected_br_pre_commit_repo_root)


def test_ensure_repo_root_env_vars_keeps_existing_ones(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.sync_skills.resolve as resolve_mod

    monkeypatch.setenv("USER_REPO_ROOT", "/existing/user")
    monkeypatch.setenv("BR_PRE_COMMIT_REPO_ROOT", "/existing/tool")

    resolve_mod._ensure_repo_root_env_vars()

    assert os.environ["USER_REPO_ROOT"] == "/existing/user"
    assert os.environ["BR_PRE_COMMIT_REPO_ROOT"] == "/existing/tool"
