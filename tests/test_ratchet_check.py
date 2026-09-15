import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/br_pre_commit/incremental_precommit"))
import ratchet_check

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


def test_mypy_records_group_by_rule_and_by_file_ignore_notes_and_summary(monkeypatch):
    monkeypatch.setattr(ratchet_check, "TARGET", "app")
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
    assert ratchet_check.loc_excess_total({"a.py": 100, "b.py": 320, "c.py": 305}) == 25


# ---- touched_app_python_files ----


def test_touched_app_python_files_parses_status_and_renames(monkeypatch, tmp_path):
    monkeypatch.setattr(ratchet_check, "TARGET", "app")
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
    after = _dicts(mypy={"app/new.py": 1})
    before = _dicts(mypy={"app/new.py": 5})

    blocked = ratchet_check.evaluate_file_gate(touched, after, before)

    assert ("mypy", Path("app/new.py"), 0, 1) in blocked


def test_loc_new_file_must_fit_under_cap(monkeypatch):
    touched = [ratchet_check.TouchedFile(path=Path("app/new.py"), is_new=True, old_path=None)]

    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 400)
    blocked = ratchet_check.evaluate_file_gate(touched, _dicts(), _dicts())
    assert ("loc-new-file", Path("app/new.py"), 0, 400) in blocked

    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 250)
    blocked = ratchet_check.evaluate_file_gate(touched, _dicts(), _dicts())
    assert not any(b[0].startswith("loc") for b in blocked)


def test_loc_slack_only_applies_once_a_file_is_already_over_the_cap(monkeypatch):
    touched = [ratchet_check.TouchedFile(path=Path("app/a.py"), is_new=False, old_path=Path("app/a.py"))]

    monkeypatch.setattr(ratchet_check, "_head_line_count", lambda relpath: 320)
    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 326)
    blocked = ratchet_check.evaluate_file_gate(touched, _dicts(), _dicts())
    assert ("loc", Path("app/a.py"), 320, 326) in blocked

    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 324)
    blocked = ratchet_check.evaluate_file_gate(touched, _dicts(), _dicts())
    assert blocked == []

    monkeypatch.setattr(ratchet_check, "_head_line_count", lambda relpath: 290)
    monkeypatch.setattr(ratchet_check, "_line_count", lambda path: 700)
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
