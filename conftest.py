import os
from pathlib import Path

import pytest


def pytest_configure(config):
    repo_root = Path(__file__).resolve().parent
    os.environ["USER_REPO_ROOT"] = str(repo_root)
    os.environ["BR_PRE_COMMIT_REPO_ROOT"] = str(repo_root)


@pytest.fixture(autouse=True, scope="session")
def set_repo_env_vars():
    repo_root = Path(__file__).resolve().parent
    os.environ["USER_REPO_ROOT"] = str(repo_root)
    os.environ["BR_PRE_COMMIT_REPO_ROOT"] = str(repo_root)
    yield
    os.environ.pop("USER_REPO_ROOT", None)
    os.environ.pop("BR_PRE_COMMIT_REPO_ROOT", None)
