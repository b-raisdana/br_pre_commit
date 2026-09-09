import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/br_pre_commit/incremental_precommit"))
import ratchet_check  # noqa: E402

pytestmark = pytest.mark.unit


# ---- pure grouping functions ----


def test_ruff_groups_by_rule_code():
    violations = [{"code": "E501"}, {"code": "E501"}, {"code": "F401"}]
    assert ratchet_check._group_ruff_by_rule(violations) == {"ruff:E501": 2, "ruff:F401": 1}


def test_ruff_groups_by_file_relativizing_absolute_filenames():
    root = Path("/repo")
    violations = [
        {"filename": "/repo/app/a.py", "code": "E501"},
        {"filename": "/repo/app/a.py", "code": "F401"},
        {"filename": "/repo/app/b.py", "code": "E501"},
    ]
    assert ratchet_check._group_ruff_by_file(violations, root=root) == {"app/a.py": 2, "app/b.py": 1}


def test_mypy_records_group_by_rule_and_by_file_ignore_notes_and_summary():
    output = "\n".join(
        [
            "a.py:1: error: bad type  [type-arg]",
            "a.py:1: error: bad type  [type-arg]",
            "b.py:2: error: no overload  [call-overload]",
            "b.py:2: note: Possible overload variants:",
            "Found 3 errors in 2 files (checked 2 source files)",
        ]
    )
    records = ratchet_check._parse_mypy_records(output)
    assert ratchet_check._group_mypy_by_rule(records) == {"mypy:type-arg": 2, "mypy:call-overload": 1}
    assert ratchet_check._group_mypy_by_file(records) == {"app/a.py": 2, "app/b.py": 1}


def test_mypy_error_without_code_falls_back_to_uncoded_bucket():
    records = ratchet_check._parse_mypy_records("a.py:1: error: something old-style with no bracket code")
    assert ratchet_check._group_mypy_by_rule(records) == {"mypy:uncoded": 1}


def test_xenon_total_and_by_file_share_the_same_threshold():
    data = {
        "app/a.py": [{"rank": "C"}, {"rank": "A"}],
        "app/b.py": [{"rank": "F"}],
    }
    assert ratchet_check._xenon_total(data) == 2
    assert ratchet_check._group_xenon_by_file(data) == {"app/a.py": 1, "app/b.py": 1}


def test_loc_excess_total_sums_only_the_overage():
    assert ratchet_check.loc_excess_total({"a.py": 300, "b.py": 520, "c.py": 505}) == 25


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


# ---- touched_app_python_files ----


def test_touched_app_python_files_parses_status_and_renames(monkeypatch, tmp_path):
    existing = "app/config/Config.py"  # a real file, so the exists() check passes
    monkeypatch.setattr(ratchet_check, "ROOT", tmp_path)
    (tmp_path / existing).parent.mkdir(parents=True)
    (tmp_path / existing).touch()
    diff_output = "\n".join(
        [
            f"M\t{existing}",
            f"A\t{existing}",
            f"R100\told/path.py\t{existing}",
            "M\tsome_other_dir/not_app.py",
        ]
    )
    monkeypatch.setattr(ratchet_check, "run", lambda *a, **k: diff_output)

    touched = ratchet_check.touched_app_python_files()

    assert len(touched) == 3
    modified = touched[0]
    assert modified.path == Path(existing) and not modified.is_new and modified.old_path == Path(existing)
    added = touched[1]
    assert added.is_new and added.old_path is None
    renamed = touched[2]
    assert not renamed.is_new and renamed.old_path == Path("old/path.py")


# ---- evaluate_file_gate ----


def _dicts(mypy=None, ruff=None, xenon=None):
    return {"mypy": mypy or {}, "ruff": ruff or {}, "xenon": xenon or {}}


def test_zero_tolerance_blocks_any_increase_for_mypy_ruff_xenon(monkeypatch):
    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 10)
    monkeypatch.setattr(ratchet_check, "_head_line_count", lambda relpath: 10)
    touched = [ratchet_check.TouchedFile(path=Path("app/a.py"), is_new=False, old_path=Path("app/a.py"))]
    after = _dicts(mypy={"app/a.py": 3})
    before = _dicts(mypy={"app/a.py": 2})

    blocked = ratchet_check.evaluate_file_gate(touched, after, before)

    assert ("mypy", Path("app/a.py"), 2, 3) in blocked


def test_equal_or_improved_count_does_not_block(monkeypatch):
    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 10)
    monkeypatch.setattr(ratchet_check, "_head_line_count", lambda relpath: 10)
    touched = [ratchet_check.TouchedFile(path=Path("app/a.py"), is_new=False, old_path=Path("app/a.py"))]
    after = _dicts(ruff={"app/a.py": 2}, xenon={"app/a.py": 1})
    before = _dicts(ruff={"app/a.py": 2}, xenon={"app/a.py": 5})

    blocked = ratchet_check.evaluate_file_gate(touched, after, before)

    assert blocked == []


def test_new_file_has_implicit_zero_before_for_mypy_ruff_xenon(monkeypatch):
    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 10)
    touched = [ratchet_check.TouchedFile(path=Path("app/new.py"), is_new=True, old_path=None)]
    # even though a same-path entry exists in "before" (shouldn't happen for a real new file,
    # but proves is_new forces before=0 rather than doing a lookup)
    after = _dicts(mypy={"app/new.py": 1})
    before = _dicts(mypy={"app/new.py": 5})

    blocked = ratchet_check.evaluate_file_gate(touched, after, before)

    assert ("mypy", Path("app/new.py"), 0, 1) in blocked


def test_loc_new_file_must_fit_under_cap(monkeypatch):
    touched = [ratchet_check.TouchedFile(path=Path("app/new.py"), is_new=True, old_path=None)]

    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 600)
    blocked = ratchet_check.evaluate_file_gate(touched, _dicts(), _dicts())
    assert ("loc-new-file", Path("app/new.py"), 0, 600) in blocked

    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 400)
    blocked = ratchet_check.evaluate_file_gate(touched, _dicts(), _dicts())
    assert not any(b[0].startswith("loc") for b in blocked)


def test_loc_slack_only_applies_once_a_file_is_already_over_the_cap(monkeypatch):
    touched = [ratchet_check.TouchedFile(path=Path("app/a.py"), is_new=False, old_path=Path("app/a.py"))]

    # already over 500, grows past the +5 slack -> blocked
    monkeypatch.setattr(ratchet_check, "_head_line_count", lambda relpath: 520)
    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 526)
    blocked = ratchet_check.evaluate_file_gate(touched, _dicts(), _dicts())
    assert ("loc", Path("app/a.py"), 520, 526) in blocked

    # already over 500, grows within the +5 slack -> not blocked
    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 524)
    blocked = ratchet_check.evaluate_file_gate(touched, _dicts(), _dicts())
    assert blocked == []

    # was under 500 before, jumps well past 500 -> not blocked by this rule (by design:
    # only the non-blocking project-wide sum notices a file crossing the cap for the first time)
    monkeypatch.setattr(ratchet_check, "_head_line_count", lambda relpath: 490)
    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 900)
    blocked = ratchet_check.evaluate_file_gate(touched, _dicts(), _dicts())
    assert blocked == []


def test_renamed_file_looks_up_before_state_under_the_old_path(monkeypatch):
    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 10)
    monkeypatch.setattr(ratchet_check, "_head_line_count", lambda relpath: 10)
    touched = [ratchet_check.TouchedFile(path=Path("app/new_name.py"), is_new=False, old_path=Path("app/old_name.py"))]
    after = _dicts(ruff={"app/new_name.py": 4})
    before = _dicts(ruff={"app/old_name.py": 4})

    blocked = ratchet_check.evaluate_file_gate(touched, after, before)

    assert blocked == []


# ---- main(): aggregate is trend-only, the file gate is what blocks ----


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
    # Old baseline file is NOT modified — a new hash-named file is written alongside it
    assert json.loads((hermetic / "baseline.json").read_text()) == {"ruff:OLD": 2}
    assert {"loc": 0, "ruff:OLD": 0, "xenon": 0} in _baseline_contents(hermetic)


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
