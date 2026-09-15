import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/br_pre_commit/incremental_precommit"))
import ratchet_check

pytestmark = pytest.mark.unit


@pytest.fixture
def hermetic(tmp_path, monkeypatch):
    monkeypatch.setattr(ratchet_check, "ROOT", tmp_path)
    monkeypatch.setattr(ratchet_check, "BASELINE_DIR", tmp_path)
    (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")
    monkeypatch.setattr(ratchet_check, "characterization_test_touched", lambda: True)
    monkeypatch.setattr(ratchet_check.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(ratchet_check, "loc_line_counts", lambda: {})
    return tmp_path


def _seed(baseline_dir: Path, data: dict[str, int]) -> Path:
    path = baseline_dir / "baseline.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return path


def _baseline_contents(baseline_dir: Path) -> list[dict[str, int]]:
    return [json.loads(f.read_text()) for f in sorted(baseline_dir.glob("baseline*.json"))]


# ---- main(): aggregate is trend-only, the file gate is what blocks ----


def test_aggregate_regression_alone_never_blocks(hermetic, monkeypatch, capsys):
    _seed(hermetic, {"ruff:E501": 3})
    monkeypatch.setattr(
        ratchet_check, "ruff_run", lambda root=None: [{"code": "E501", "filename": "/repo/app/a.py"}] * 5
    )
    monkeypatch.setattr(ratchet_check, "mypy_run", lambda root=None: [])
    monkeypatch.setattr(ratchet_check, "xenon_run", lambda root=None: {})
    monkeypatch.setattr(ratchet_check, "touched_app_python_files", lambda: [])

    exit_code = ratchet_check.main()

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "BLOCKED" not in out
    assert "trend only, does not block" in out


def test_touched_file_regression_blocks_even_with_no_prior_baseline(hermetic, monkeypatch, capsys):
    absolute_path = str(ratchet_check.ROOT / "app/a.py")
    monkeypatch.setattr(ratchet_check, "ruff_run", lambda root=None: [{"code": "E501", "filename": absolute_path}])
    monkeypatch.setattr(ratchet_check, "mypy_run", lambda root=None: [])
    monkeypatch.setattr(ratchet_check, "xenon_run", lambda root=None: {})
    monkeypatch.setattr(
        ratchet_check,
        "touched_app_python_files",
        lambda: [ratchet_check.TouchedFile(path=Path("app/a.py"), is_new=False, old_path=Path("app/a.py"))],
    )
    monkeypatch.setattr(ratchet_check, "_head_worktree", lambda: None)
    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 10)
    monkeypatch.setattr(ratchet_check, "_head_line_count", lambda relpath: 10)
    monkeypatch.setattr(ratchet_check, "run_output", lambda *a, **k: "")

    exit_code = ratchet_check.main()

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "ruff in app/a.py: 0 -> 1" in out


def test_touched_file_with_no_regression_passes_and_resyncs_baseline(hermetic, monkeypatch):
    _seed(hermetic, {"ruff:OLD": 2})
    monkeypatch.setattr(ratchet_check, "ruff_run", lambda root=None: [])
    monkeypatch.setattr(ratchet_check, "mypy_run", lambda root=None: [])
    monkeypatch.setattr(ratchet_check, "xenon_run", lambda root=None: {})
    monkeypatch.setattr(
        ratchet_check,
        "touched_app_python_files",
        lambda: [ratchet_check.TouchedFile(path=Path("app/a.py"), is_new=False, old_path=Path("app/a.py"))],
    )
    monkeypatch.setattr(ratchet_check, "_head_worktree", lambda: None)
    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 10)
    monkeypatch.setattr(ratchet_check, "_head_line_count", lambda relpath: 10)

    exit_code = ratchet_check.main()

    assert exit_code == 0
    assert json.loads((hermetic / "baseline.json").read_text()) == {"ruff:OLD": 2}
    assert {"loc": 0, "ruff:OLD": 0, "xenon": 0} in _baseline_contents(hermetic)


# ---- analyzer concurrency tests ----


def test_current_analyzers_start_concurrently(monkeypatch):
    barrier = threading.Barrier(4)

    def completed(value):
        barrier.wait(timeout=1)
        return value

    monkeypatch.setattr(ratchet_check, "ruff_run", lambda: completed([]))
    monkeypatch.setattr(ratchet_check, "mypy_run", lambda: completed([]))
    monkeypatch.setattr(ratchet_check, "xenon_run", lambda: completed({}))
    monkeypatch.setattr(ratchet_check, "loc_line_counts", lambda: completed({}))

    assert ratchet_check._run_current_analyzers() == ([], [], {}, {})


def test_current_and_before_analyzers_start_concurrently(monkeypatch, tmp_path):
    barrier = threading.Barrier(7)

    def completed(value):
        barrier.wait(timeout=1)
        return value

    monkeypatch.setattr(ratchet_check, "ruff_run", lambda root=ratchet_check.ROOT: completed([]))
    monkeypatch.setattr(ratchet_check, "mypy_run", lambda root=ratchet_check.ROOT: completed([]))
    monkeypatch.setattr(ratchet_check, "xenon_run", lambda root=ratchet_check.ROOT: completed({}))
    monkeypatch.setattr(ratchet_check, "loc_line_counts", lambda root=ratchet_check.ROOT: completed({}))

    assert ratchet_check._run_current_and_before_analyzers(tmp_path) == (
        [],
        [],
        {},
        {},
        {"mypy": {}, "ruff": {}, "xenon": {}},
    )


# ---- multi-file baseline management ----


def test_merge_baselines_takes_union_with_minimum_per_key():
    a = {"ruff:E501": 3, "loc": 0}
    b = {"ruff:E501": 5, "mypy:arg-type": 2}
    assert ratchet_check.merge_baselines([a, b]) == {"loc": 0, "mypy:arg-type": 2, "ruff:E501": 3}


def test_merge_baselines_single_dict_is_identity():
    data = {"loc": 0, "ruff:E501": 3}
    assert ratchet_check.merge_baselines([data]) == {"loc": 0, "ruff:E501": 3}


def test_compute_new_baseline_never_loses_vector_when_count_drops_to_zero():
    old = {"ruff:E501": 3, "loc": 0}
    current = {"loc": 0, "xenon": 2}
    result = ratchet_check.compute_new_baseline(old, current)
    assert result == {"loc": 0, "ruff:E501": 0, "xenon": 2}


def test_compute_new_baseline_keeps_best_value_when_count_regresses():
    old = {"ruff:E501": 3}
    current = {"ruff:E501": 5, "loc": 0, "xenon": 0}
    result = ratchet_check.compute_new_baseline(old, current)
    assert result == {"loc": 0, "ruff:E501": 3, "xenon": 0}


def test_compute_new_baseline_locks_in_improvement():
    old = {"ruff:E501": 3}
    current = {"ruff:E501": 1, "loc": 0, "xenon": 0}
    result = ratchet_check.compute_new_baseline(old, current)
    assert result == {"loc": 0, "ruff:E501": 1, "xenon": 0}


def test_compute_new_baseline_bootsraps_new_key():
    old = {}
    current = {"loc": 0, "xenon": 2}
    result = ratchet_check.compute_new_baseline(old, current)
    assert result == {"loc": 0, "xenon": 2}


def test_baseline_filename_is_deterministic_hash_of_content():
    data = {"loc": 0, "ruff:E501": 3}
    name1 = ratchet_check.baseline_filename(data)
    name2 = ratchet_check.baseline_filename(dict(reversed(list(data.items()))))
    assert name1 == name2


def test_load_and_consolidate_merges_multiple_files_and_removes_old(hermetic):
    _seed(hermetic, {"ruff:E501": 3, "loc": 0})
    other = hermetic / "baseline_abcdef12.json"
    other.write_text(json.dumps({"ruff:E501": 5, "mypy:arg-type": 2}))

    result = ratchet_check.load_and_consolidate_baselines()

    assert result == {"loc": 0, "mypy:arg-type": 2, "ruff:E501": 3}
    files = ratchet_check.find_baseline_files()
    assert len(files) == 1
    assert json.loads(files[0].read_text()) == {"loc": 0, "mypy:arg-type": 2, "ruff:E501": 3}
    assert not (hermetic / "baseline.json").exists()
    assert not other.exists()


def test_load_and_consolidate_single_file_is_untouched(hermetic):
    _seed(hermetic, {"ruff:OLD": 2})
    original = (hermetic / "baseline.json").read_text()

    result = ratchet_check.load_and_consolidate_baselines()

    assert result == {"ruff:OLD": 2}
    assert (hermetic / "baseline.json").read_text() == original
    assert len(ratchet_check.find_baseline_files()) == 1


def test_load_and_consolidate_no_files_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(ratchet_check, "BASELINE_DIR", tmp_path)
    assert ratchet_check.load_and_consolidate_baselines() == {}
