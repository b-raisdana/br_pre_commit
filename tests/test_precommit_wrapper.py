import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

HOOK_DIR = Path(__file__).resolve().parents[1] / "src/br_pre_commit"
sys.path.insert(0, str(HOOK_DIR))
SPEC = importlib.util.spec_from_file_location("precommit_wrapper", HOOK_DIR / "precommit_wrapper.py")
assert SPEC is not None and SPEC.loader is not None
precommit_wrapper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = precommit_wrapper
SPEC.loader.exec_module(precommit_wrapper)

pytestmark = pytest.mark.unit


def test_branch_protection_blocks_main_by_default(monkeypatch):
    monkeypatch.setattr(precommit_wrapper, "protected_branches", lambda _root: ("main",))

    result = precommit_wrapper._branch_protection_result("main")

    assert result is not None
    assert result.job_id == "branch-protection"
    assert result.returncode == 1


def test_branch_protection_allows_feature_branch(monkeypatch):
    monkeypatch.setattr(precommit_wrapper, "protected_branches", lambda _root: ("main",))

    assert precommit_wrapper._branch_protection_result("feature/readmes") is None


def test_hook_command_uses_explicit_files_to_avoid_nested_stash():
    command = precommit_wrapper._hook_command("pytest-fast", ["app/a.py", "app/b.py"])

    assert command[-3:] == ["--files", "app/a.py", "app/b.py"]


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
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"


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
    monkeypatch.setattr(precommit_wrapper, "LOG_DIR", tmp_path)
    results = [
        precommit_wrapper.JobResult("first", ("one",), 0, 0.1, "first-out", "first-err"),
        precommit_wrapper.JobResult("second", ("two",), 1, 0.2, "second-out", "second-err"),
    ]

    report = precommit_wrapper._write_report("stamp", results).read_text()

    assert report.index("## first") < report.index("## second")
    assert "first-out" in report and "second-err" in report


def test_advisory_warnings_parse_ruff_and_radon_results(monkeypatch, tmp_path):
    monkeypatch.setattr(precommit_wrapper, "REPO_ROOT", tmp_path)
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

    assert precommit_wrapper._advisory_warnings(results) == [
        {"file": "app/module.py", "line": 7, "code": "ERA001", "message": "commented code"},
        {
            "file": "app/module.py",
            "line": 0,
            "code": "radon-mi-B",
            "message": "Maintainability Index: 12.34 (B)",
        },
    ]


def test_run_hooks_finishes_mutators_before_starting_read_only_jobs(monkeypatch):
    calls = []
    both_readers_started = asyncio.Event()
    readers = 0

    monkeypatch.setattr(precommit_wrapper, "unknown_hook_policy", lambda _root: "error")
    monkeypatch.setattr(precommit_wrapper, "job_timeout_seconds", lambda _root: 10)
    monkeypatch.setattr(
        precommit_wrapper, "enabled_pre_commit_hook_ids", lambda _path: ["ruff", "pytest-fast", "check-yaml"]
    )

    async def fake_run(job_id, command, lock, *, stream_output=True, timeout_seconds=None):
        nonlocal readers
        calls.append(f"start:{job_id}")
        if job_id == "ruff":
            calls.append("finish:ruff")
        else:
            readers += 1
            if readers == 2:
                both_readers_started.set()
            await asyncio.wait_for(both_readers_started.wait(), timeout=1)
            calls.append(f"finish:{job_id}")
        return precommit_wrapper.JobResult(job_id, tuple(command), 0, 0.0, "", "")

    monkeypatch.setattr(precommit_wrapper, "_run_job", fake_run)

    results = asyncio.run(precommit_wrapper._run_hooks(["README.md"]))

    assert calls.index("finish:ruff") < calls.index("start:pytest-fast")
    assert calls.index("finish:ruff") < calls.index("start:check-yaml")
    assert [result.job_id for result in results] == ["ruff", "pytest-fast", "check-yaml"]
