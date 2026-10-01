import json
import sys
import threading
from pathlib import Path

import pytest

import helper.paths as paths_module
import ratchet.common as common_module
from ratchet.__main__ import main
from ratchet.common import (
    TouchedFile,
    baseline_filename,
    compute_new_baseline,
    find_baseline_files,
    load_and_consolidate_baselines,
    merge_baselines,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


pytestmark = [pytest.mark.unit, pytest.mark.ratchet]


@pytest.fixture
def hermetic(tmp_path, monkeypatch):
    """Point ratchet at a throwaway repo root with an empty, writable baseline dir."""
    import ratchet.__main__ as main_module
    import ratchet.gate as gate_module
    import ratchet.tools as tools_module

    monkeypatch.setattr(paths_module, "get_ratchet_baseline_dir", lambda: tmp_path)
    for module in (common_module, gate_module, tools_module):
        monkeypatch.setattr(module, "get_user_repo_path_from_env", lambda: tmp_path)
    monkeypatch.setattr(common_module.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "_validate_configured_hooks", lambda: [])
    monkeypatch.setattr(main_module, "characterization_test_touched", lambda: False)
    _block_details_off(monkeypatch)
    return tmp_path


def _seed(baseline_dir: Path, data: dict[str, int]) -> Path:
    path = baseline_dir / baseline_filename(data)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _baseline_contents(baseline_dir: Path) -> list[dict[str, int]]:
    return [json.loads(f.read_text()) for f in sorted(baseline_dir.glob("baseline*.json"))]


def _block_details_off(monkeypatch):
    # details.py reaches for helper symbols on the baseline module that no longer exist
    # there, so the detail printers would raise. They are not under test here.
    monkeypatch.setattr(
        common_module,
        "DETAIL_PRINTERS",
        {tool: lambda paths: None for tool in ("ruff", "mypy", "xenon", "loc")},
    )


# ---- main(): aggregate is trend-only, the file gate is what blocks ----


def test_aggregate_regression_alone_never_blocks(hermetic, monkeypatch, capsys):
    import ratchet.__main__ as main_module
    import ratchet.tools as tools_module

    _seed(hermetic, {"ruff:E501": 3})
    monkeypatch.setattr(
        tools_module,
        "ruff_run",
        lambda root=None: [{"filename": "/repo/src/a.py", "code": "E501"}] * 5,
    )
    monkeypatch.setattr(tools_module, "mypy_run", lambda root=None: [])
    monkeypatch.setattr(tools_module, "xenon_run", lambda root=None: {})
    monkeypatch.setattr(tools_module, "loc_line_counts", lambda root=None: {})
    monkeypatch.setattr(main_module, "touched_app_python_files", lambda: [])

    exit_code = main()

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "BLOCKED" not in out
    assert "trend only, does not block" in out


def test_touched_file_regression_blocks_even_with_no_prior_baseline(hermetic, monkeypatch, capsys):
    import ratchet.__main__ as main_module
    import ratchet.tools as tools_module

    _block_details_off(monkeypatch)
    touched = [TouchedFile(path=Path("src/a.py"), is_new=False, old_path=Path("src/a.py"))]
    monkeypatch.setattr(
        tools_module,
        "ruff_run",
        lambda root=None: [{"filename": str(hermetic / "src/a.py"), "code": "E501"}],
    )
    monkeypatch.setattr(tools_module, "mypy_run", lambda root=None: [])
    monkeypatch.setattr(tools_module, "xenon_run", lambda root=None: {})
    monkeypatch.setattr(tools_module, "loc_line_counts", lambda root=None: {})
    monkeypatch.setattr(main_module, "touched_app_python_files", lambda: touched)
    monkeypatch.setattr(main_module, "_head_worktree", lambda: None)
    monkeypatch.setattr(common_module, "count_lines", lambda path: 10)
    monkeypatch.setattr("ratchet.gate._head_line_count", lambda relpath: 10)

    exit_code = main()

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "ruff in src/a.py: 0 -> 1" in out


def test_touched_file_with_no_regression_passes_and_resyncs_baseline(hermetic, monkeypatch):
    import ratchet.__main__ as main_module
    import ratchet.tools as tools_module

    _block_details_off(monkeypatch)
    _seed(hermetic, {"ruff:OLD": 2})
    touched = [TouchedFile(path=Path("src/a.py"), is_new=False, old_path=Path("src/a.py"))]
    monkeypatch.setattr(tools_module, "ruff_run", lambda root=None: [])
    monkeypatch.setattr(tools_module, "mypy_run", lambda root=None: [])
    monkeypatch.setattr(tools_module, "xenon_run", lambda root=None: {})
    monkeypatch.setattr(tools_module, "loc_line_counts", lambda root=None: {})
    monkeypatch.setattr(main_module, "touched_app_python_files", lambda: touched)
    monkeypatch.setattr(main_module, "_head_worktree", lambda: None)
    monkeypatch.setattr(common_module, "count_lines", lambda path: 10)
    monkeypatch.setattr("ratchet.gate._head_line_count", lambda relpath: 10)

    exit_code = main()

    # No touched file regressed, so the run passes. ruff:OLD counted 0 against a baseline of
    # 2, so the ratcheted baseline drops the key and is written as its own content-addressed
    # file; the stale file stays until the next load_and_consolidate_baselines() folds it in.
    assert exit_code == 0
    assert _baseline_contents(hermetic) == [{"ruff:OLD": 2}, {}]


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

    from ratchet.tools import run_current_analyzers

    assert run_current_analyzers() == ([], [], {}, {})


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
    from ratchet.common import baseline_filename

    data = {"loc": 0, "ruff:E501": 3}
    name1 = baseline_filename(data)
    name2 = baseline_filename(dict(reversed(list(data.items()))))
    assert name1 == name2


def test_load_and_consolidate_merges_multiple_files_and_removes_old(hermetic):
    first = _seed(hermetic, {"ruff:E501": 3})
    second = _seed(hermetic, {"mypy:arg-type": 2, "ruff:E501": 5})

    result = load_and_consolidate_baselines()

    # Merge takes the minimum per key and drops zero-valued keys.
    assert result == {"mypy:arg-type": 2, "ruff:E501": 3}
    remaining = find_baseline_files()
    assert len(remaining) == 1
    assert remaining[0].name == baseline_filename(result)
    assert json.loads(remaining[0].read_text(encoding="utf-8")) == result
    assert not first.exists()
    assert not second.exists()


def test_load_and_consolidate_single_file_is_untouched(hermetic):
    seeded = _seed(hermetic, {"ruff:OLD": 2})
    original = seeded.read_text(encoding="utf-8")

    result = load_and_consolidate_baselines()

    assert result == {"ruff:OLD": 2}
    assert seeded.read_text(encoding="utf-8") == original
    assert len(find_baseline_files()) == 1


def test_load_and_consolidate_no_files_returns_empty(hermetic):
    assert load_and_consolidate_baselines() == {}
