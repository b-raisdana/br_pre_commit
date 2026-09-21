import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ratchet import (
    TouchedFile,
    compute_new_baseline,
    find_baseline_files,
    load_and_consolidate_baselines,
    merge_baselines,
)

pytestmark = pytest.mark.unit


# @pytest.fixture
# def hermetic(tmp_path, monkeypatch):
#     import ratchet.baseline as baseline_module
#     import ratchet.gate as gate_module
#     import ratchet.tools as tools_module
#
#     monkeypatch.setattr(baseline_module, "ROOT", tmp_path)
#     monkeypatch.setattr(baseline_module, "BASELINE_DIR", tmp_path)
#     monkeypatch.setattr(gate_module, "ROOT", tmp_path)
#     monkeypatch.setattr(tools_module, "ROOT", tmp_path)
#     (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")
#     monkeypatch.setattr(gate_module, "characterization_test_touched", lambda: True)
#     import subprocess
#
#     monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
#     monkeypatch.setattr(tools_module, "loc_line_counts", lambda: {})
#     return tmp_path


def _seed(baseline_dir: Path, data: dict[str, int]) -> Path:
    path = baseline_dir / "baseline.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return path


def _baseline_contents(baseline_dir: Path) -> list[dict[str, int]]:
    return [json.loads(f.read_text()) for f in sorted(baseline_dir.glob("baseline*.json"))]


# ---- main(): aggregate is trend-only, the file gate is what blocks ----


def test_aggregate_regression_alone_never_blocks(hermetic, monkeypatch, capsys):
    _seed(hermetic, {"ruff:E501": 3})
    import ratchet.gate as gate_module
    import ratchet.tools as tools_module

    monkeypatch.setattr(
        tools_module, "ruff_run", lambda root=None: [{"code": "E501", "filename": "/repo/app/a.py"}] * 5
    )
    monkeypatch.setattr(tools_module, "mypy_run", lambda root=None: [])
    monkeypatch.setattr(tools_module, "xenon_run", lambda root=None: {})
    monkeypatch.setattr(gate_module, "touched_app_python_files", lambda: [])

    from ratchet.__main__ import main

    exit_code = main()

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "BLOCKED" not in out
    assert "trend only, does not block" in out


def test_touched_file_regression_blocks_even_with_no_prior_baseline(hermetic, monkeypatch, capsys):
    import ratchet.baseline as baseline_module
    import ratchet.gate as gate_module
    import ratchet.tools as tools_module

    absolute_path = str(hermetic / "app/a.py")
    monkeypatch.setattr(tools_module, "ruff_run", lambda root=None: [{"code": "E501", "filename": absolute_path}])
    monkeypatch.setattr(tools_module, "mypy_run", lambda root=None: [])
    monkeypatch.setattr(tools_module, "xenon_run", lambda root=None: {})
    monkeypatch.setattr(
        gate_module,
        "touched_app_python_files",
        lambda: [TouchedFile(path=Path("app/a.py"), is_new=False, old_path=Path("app/a.py"))],
    )
    monkeypatch.setattr(gate_module, "_head_worktree", lambda: None)
    monkeypatch.setattr(baseline_module, "_line_count", lambda path: 10)
    monkeypatch.setattr(gate_module, "_head_line_count", lambda relpath: 10)
    monkeypatch.setattr(baseline_module, "run_output", lambda *a, **k: "")

    from ratchet.__main__ import main

    exit_code = main()

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "ruff in app/a.py: 0 -> 1" in out


def test_touched_file_with_no_regression_passes_and_resyncs_baseline(hermetic, monkeypatch):
    _seed(hermetic, {"ruff:OLD": 2})
    import ratchet.baseline as baseline_module
    import ratchet.gate as gate_module
    import ratchet.tools as tools_module

    monkeypatch.setattr(tools_module, "ruff_run", lambda root=None: [])
    monkeypatch.setattr(tools_module, "mypy_run", lambda root=None: [])
    monkeypatch.setattr(tools_module, "xenon_run", lambda root=None: {})
    monkeypatch.setattr(
        gate_module,
        "touched_app_python_files",
        lambda: [TouchedFile(path=Path("app/a.py"), is_new=False, old_path=Path("app/a.py"))],
    )
    monkeypatch.setattr(gate_module, "_head_worktree", lambda: None)
    monkeypatch.setattr(baseline_module, "_line_count", lambda path: 10)
    monkeypatch.setattr(gate_module, "_head_line_count", lambda relpath: 10)

    from ratchet.__main__ import main

    exit_code = main()

    assert exit_code == 0
    assert json.loads((hermetic / "baseline.json").read_text()) == {"ruff:OLD": 2}
    assert {} in _baseline_contents(hermetic)


# ---- analyzer concurrency tests ----


def test_current_analyzers_start_concurrently(monkeypatch):
    barrier = threading.Barrier(4)

    def completed(value):
        barrier.wait(timeout=1)
        return value

    import ratchet.tools as tools_module

    monkeypatch.setattr(tools_module, "ruff_run", lambda: completed([]))
    monkeypatch.setattr(tools_module, "mypy_run", lambda: completed([]))
    monkeypatch.setattr(tools_module, "xenon_run", lambda: completed({}))
    monkeypatch.setattr(tools_module, "loc_line_counts", lambda: completed({}))

    from ratchet.tools import _run_current_analyzers

    assert _run_current_analyzers() == ([], [], {}, {})


def test_current_and_before_analyzers_start_concurrently(monkeypatch, tmp_path):
    barrier = threading.Barrier(7)

    def completed(value):
        barrier.wait(timeout=1)
        return value

    import ratchet.tools as tools_module

    monkeypatch.setattr(tools_module, "ruff_run", lambda root=None: completed([]))
    monkeypatch.setattr(tools_module, "mypy_run", lambda root=None: completed([]))
    monkeypatch.setattr(tools_module, "xenon_run", lambda root=None: completed({}))
    monkeypatch.setattr(tools_module, "loc_line_counts", lambda root=None: completed({}))

    from ratchet.tools import _run_current_and_before_analyzers

    assert _run_current_and_before_analyzers(tmp_path) == (
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
    assert merge_baselines([a, b]) == {"loc": 0, "mypy:arg-type": 2, "ruff:E501": 3}


def test_merge_baselines_single_dict_is_identity():
    data = {"loc": 0, "ruff:E501": 3}
    assert merge_baselines([data]) == {"loc": 0, "ruff:E501": 3}


def test_compute_new_baseline_drops_key_when_count_reaches_zero():
    old = {"ruff:E501": 3, "loc": 0}
    current = {"loc": 0, "xenon": 2}
    result = compute_new_baseline(old, current)
    assert result == {"xenon": 2}


def test_compute_new_baseline_keeps_best_value_when_count_regresses():
    old = {"ruff:E501": 3}
    current = {"ruff:E501": 5, "loc": 0, "xenon": 0}
    result = compute_new_baseline(old, current)
    assert result == {"ruff:E501": 3}


def test_compute_new_baseline_locks_in_improvement():
    old = {"ruff:E501": 3}
    current = {"ruff:E501": 1, "loc": 0, "xenon": 0}
    result = compute_new_baseline(old, current)
    assert result == {"ruff:E501": 1}


def test_compute_new_baseline_bootsraps_new_key():
    old = {}
    current = {"loc": 0, "xenon": 2}
    result = compute_new_baseline(old, current)
    assert result == {"xenon": 2}


def test_baseline_filename_is_deterministic_hash_of_content():
    from ratchet.baseline import baseline_filename

    data = {"loc": 0, "ruff:E501": 3}
    name1 = baseline_filename(data)
    name2 = baseline_filename(dict(reversed(list(data.items()))))
    assert name1 == name2


def test_load_and_consolidate_merges_multiple_files_and_removes_old(hermetic):
    _seed(hermetic, {"ruff:E501": 3, "loc": 0})
    other = hermetic / "baseline_abcdef12.json"
    other.write_text(json.dumps({"ruff:E501": 5, "mypy:arg-type": 2}))

    result = load_and_consolidate_baselines()

    assert result == {"mypy:arg-type": 2, "ruff:E501": 3}
    files = find_baseline_files()
    assert len(files) == 1
    assert json.loads(files[0].read_text()) == {"mypy:arg-type": 2, "ruff:E501": 3}
    assert not (hermetic / "baseline.json").exists()
    assert not other.exists()


def test_load_and_consolidate_single_file_is_untouched(hermetic):
    _seed(hermetic, {"ruff:OLD": 2})
    original = (hermetic / "baseline.json").read_text()

    result = load_and_consolidate_baselines()

    assert result == {"ruff:OLD": 2}
    assert (hermetic / "baseline.json").read_text() == original
    assert len(find_baseline_files()) == 1


# def test_load_and_consolidate_no_files_returns_empty(tmp_path, monkeypatch):
#     import ratchet.baseline as baseline_module
#
#     monkeypatch.setattr(baseline_module, "BASELINE_DIR", tmp_path)
#     assert load_and_consolidate_baselines() == {}
