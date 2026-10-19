import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from src.helper.git import InvalidGitRepositoryError, get_repo_sync, run_git

pytestmark = pytest.mark.unit


def test_run_git_scrubs_hook_environment_and_preserves_index_by_default(tmp_path: Path):
    with (
        patch("src.helper.git.git_subprocess_env", return_value={"GIT_INDEX_FILE": "custom-index"}) as env,
        patch("src.helper.git.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "ok", "")) as run,
    ):
        result = run_git("status", git_repo_root=tmp_path)

    assert result.stdout == "ok"
    env.assert_called_once_with(inherit_index=True)
    assert run.call_args.args[0] == ["git", "-C", str(tmp_path), "status"]
    assert run.call_args.kwargs["env"] == {"GIT_INDEX_FILE": "custom-index"}
    assert run.call_args.kwargs["text"] is True


def test_run_git_can_return_bytes_without_scrubbing_environment(tmp_path: Path):
    with (
        patch("src.helper.git.git_subprocess_env") as env,
        patch("src.helper.git.subprocess.run", return_value=subprocess.CompletedProcess([], 0, b"ok", b"")) as run,
    ):
        result = run_git("show", ":file", git_repo_root=tmp_path, text=False, scrub_environment=False)

    assert result.stdout == b"ok"
    env.assert_not_called()
    assert run.call_args.kwargs["text"] is False
    assert run.call_args.kwargs.get("env") is None


def test_get_repo_sync_translates_invalid_repository_error(tmp_path: Path):
    failure = subprocess.CalledProcessError(128, ["git"], stderr="not a repository")
    with (
        patch("src.helper.git.run_git", side_effect=failure),
        pytest.raises(InvalidGitRepositoryError, match=f"{tmp_path} is not a git repository"),
    ):
        get_repo_sync(tmp_path)
