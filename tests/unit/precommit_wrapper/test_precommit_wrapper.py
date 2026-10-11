import asyncio
import sys
from types import SimpleNamespace

import pytest

import src.precommit_wrapper.__main__ as precommit_wrapper
from src.precommit_wrapper import report

pytestmark = [pytest.mark.unit, pytest.mark.precommit_wrapper]


def test_branch_protection_blocks_main_by_default(monkeypatch):
    monkeypatch.setattr(precommit_wrapper.wrapper_config, "protected_branches_regex", "^(main|develop|uat)$")
    monkeypatch.setattr(
        precommit_wrapper.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )

    result = precommit_wrapper._branch_protection_result("main")

    assert result is not None
    assert result.job_id == "branch-protection"
    assert result.returncode == 1


def test_branch_protection_blocks_develop_and_uat(monkeypatch):
    monkeypatch.setattr(precommit_wrapper.wrapper_config, "protected_branches_regex", "^(main|develop|uat)$")
    monkeypatch.setattr(
        precommit_wrapper.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )

    for branch in ("develop", "uat"):
        result = precommit_wrapper._branch_protection_result(branch)
        assert result is not None
        assert result.returncode == 1


def test_branch_protection_allows_feature_branch(monkeypatch):
    monkeypatch.setattr(precommit_wrapper.wrapper_config, "protected_branches_regex", "^(main|develop|uat)$")

    assert precommit_wrapper._branch_protection_result("feature/test") is None


def test_branch_protection_allows_merge_into_main(monkeypatch):
    monkeypatch.setattr(precommit_wrapper.wrapper_config, "protected_branches_regex", "^(main|develop|uat)$")
    monkeypatch.setattr(
        precommit_wrapper.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    assert precommit_wrapper._branch_protection_result("main") is None


def test_branch_protection_rejects_partial_branch_name_match(monkeypatch):
    monkeypatch.setattr(precommit_wrapper.wrapper_config, "protected_branches_regex", "^(main|develop|uat)$")
    monkeypatch.setattr(
        precommit_wrapper.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )

    for branch in ("main-foo", "feature/main", "developing"):
        assert precommit_wrapper._branch_protection_result(branch) is None


def test_pipeline_command_runs_all_precommit_hooks_once_with_explicit_files():
    command = precommit_wrapper._pipeline_command(["src/a.py", "README.md"])

    assert command == [
        "pre-commit",
        "run",
        "--hook-stage",
        "pre-commit",
        "--color",
        "never",
        "--files",
        "src/a.py",
        "README.md",
    ]


def test_run_job_keeps_stdout_and_stderr_in_memory():
    async def run():
        return await precommit_wrapper._run_job(
            "fake",
            [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
            asyncio.Lock(),
            stream_output=False,
        )

    result = asyncio.run(run())

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["out"]
    assert result.stderr.splitlines() == ["err"]


def test_run_job_terminates_after_timeout():
    async def run():
        return await precommit_wrapper._run_job(
            "slow",
            [sys.executable, "-c", "import time; time.sleep(10)"],
            asyncio.Lock(),
            stream_output=False,
            timeout_seconds=0.01,
        )

    result = asyncio.run(run())

    assert result.returncode == 124
    assert "timed out" in result.stderr


def test_write_report_orders_results_and_preserves_streams(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "get_log_dir", lambda: tmp_path)
    results = [
        precommit_wrapper.JobResult("first", ("one",), 0, 0.1, "first-out", "first-err"),
        precommit_wrapper.JobResult("second", ("two",), 1, 0.2, "second-out", "second-err"),
    ]

    report_path = report._write_report("stamp", results)
    text = report_path.read_text(encoding="utf-8")

    assert report_path == tmp_path / "pre-commit-runs" / "stamp.log"
    assert text.index("## first") < text.index("## second")
    assert "first-out" in text and "second-err" in text


def test_advisory_warnings_parse_ruff_and_radon_results(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "get_user_repo_path_from_env", lambda: tmp_path)
    source = tmp_path / "app" / "module.py"
    results = [
        precommit_wrapper.JobResult(
            "advisory-ruff",
            (),
            1,
            0.0,
            '[{"filename": "'
            + source.as_posix()
            + '", "location": {"row": 7}, "code": "ERA001", "message": "commented code"}]',
            "",
        ),
        precommit_wrapper.JobResult("advisory-radon", (), 0, 0.0, "app/module.py - B (12.34)\n", ""),
    ]

    assert report._advisory_warnings(results) == [
        {"file": "app/module.py", "line": 7, "code": "ERA001", "message": "commented code"},
        {
            "file": "app/module.py",
            "line": 0,
            "code": "radon-mi-B",
            "message": "Maintainability Index: 12.34 (B)",
        },
    ]


def test_run_hooks_runs_one_pipeline_and_advisories(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(precommit_wrapper.wrapper_config, "job_timeout_seconds", 10)
    monkeypatch.setattr(precommit_wrapper, "get_user_repo_path_from_env", lambda: tmp_path)
    source = tmp_path / "src" / "a.py"
    source.parent.mkdir()
    source.write_text("pass\n", encoding="utf-8")

    async def fake_run(job_id, command, lock, *, stream_output=True, timeout_seconds=None):
        calls.append((job_id, command))
        return precommit_wrapper.JobResult(job_id, tuple(command), 0, 0.0, "", "")

    monkeypatch.setattr(precommit_wrapper, "_run_job", fake_run)

    results = asyncio.run(precommit_wrapper._run_hooks(["src/a.py", "README.md"]))

    pipeline_calls = [command for job_id, command in calls if job_id == "pre-commit"]
    assert pipeline_calls == [precommit_wrapper._pipeline_command(["src/a.py", "README.md"])]
    assert [result.job_id for result in results] == ["pre-commit", "advisory-ruff", "advisory-radon"]
