"""Tests for the br_pre_commit installer's environment checks."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest import mock

import pytest

INSTALL_MODULE = "br_pre_commit.install.install"
INSTALL_DIR = Path(__file__).resolve().parents[1] / "install"


def _load_install_module():
    """Import install.py by path so the test does not depend on PYTHONPATH."""
    spec = importlib.util.spec_from_file_location(INSTALL_MODULE, INSTALL_DIR / "install.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[INSTALL_MODULE] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def install():
    return _load_install_module()


def test_required_packages_mirror_requirements_txt(install):
    """REQUIRED_PACKAGES must match the import names implied by requirements.txt."""
    expected = {
        "yaml",  # pyyaml
        "pre_commit",  # pre-commit
        "radon",
        "ruff",
        "mypy",
        "pytest",
        "pytest_asyncio",  # pytest-asyncio
    }
    assert set(install.REQUIRED_PACKAGES) == expected


def test_verify_requirements_empty_when_all_present(install):
    """When every required package is importable, verify_requirements returns []."""
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name in install.REQUIRED_PACKAGES:
            return mock.MagicMock()
        return real_find_spec(name, *args, **kwargs)

    with mock.patch.object(importlib.util, "find_spec", side_effect=fake_find_spec):
        assert install.verify_requirements() == []


def test_verify_requirements_reports_missing(install):
    """verify_requirements includes the import names that are not importable."""
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name in {"yaml", "radon"}:
            return None
        return real_find_spec(name, *args, **kwargs)

    with mock.patch.object(importlib.util, "find_spec", side_effect=fake_find_spec):
        missing = install.verify_requirements()

    # yaml and radon are reported missing; everything else is whatever the real
    # environment has (the test does not assert a clean environment).
    assert "yaml" in missing
    assert "radon" in missing
    assert set(missing).issubset(set(install.REQUIRED_PACKAGES))


def test_install_aborts_on_missing_requirements(install, capsys):
    """install() returns 1 and prints an error when packages are missing."""
    with mock.patch.object(install, "verify_requirements", return_value=["yaml", "radon"]), \
         mock.patch.object(install, "get_user_repo_root", side_effect=AssertionError("should not reach git")):
        result = install.install(None, force=False, dry_run=False)

    assert result == 1
    captured = capsys.readouterr()
    assert "yaml" in captured.out and "radon" in captured.out


def test_install_skips_git_lookup_in_dry_run_when_requirements_missing(install, capsys):
    """Even --dry-run must not proceed when the environment is incomplete."""
    with mock.patch.object(install, "verify_requirements", return_value=["radon"]), \
         mock.patch.object(install, "get_user_repo_root", side_effect=AssertionError("should not reach git")):
        result = install.install(None, force=False, dry_run=True)

    assert result == 1
