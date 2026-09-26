import subprocess
from functools import lru_cache
from pathlib import Path

from config import br_pre_commit_config


@lru_cache
def get_user_repo_path_from_env() -> Path:
    repo_root = br_pre_commit_config.user_repo_root
    if not repo_root:
        raise ValueError("USER_REPO_ROOT environment variable is required")
    # repo_root = Path(__file__).resolve().parent.parent
    return Path(repo_root).resolve()


@lru_cache
def get_br_pre_commit_repo_path_from_env() -> Path:
    repo_root = br_pre_commit_config.br_pre_commit_repo_root
    if not repo_root:
        raise ValueError("BR_PRE_COMMIT_REPO_ROOT environment variable is required")

    return Path(repo_root).resolve()


@lru_cache
def get_log_dir() -> Path:
    return get_user_repo_path_from_env() / "logs" / "pre-commit"


@lru_cache
def get_log_file() -> Path:
    return get_log_dir() / "pre-commit"


@lru_cache
def get_pre_commit_config_yaml_path() -> Path:
    return get_user_repo_path_from_env() / br_pre_commit_config.pre_commit_config_yaml_file_name
    # ".pre-commit-config.yaml"


@lru_cache
def get_pyproject_toml_path() -> Path:
    return get_user_repo_path_from_env() / br_pre_commit_config.py_project_toml_file_name  # "pyproject.toml"


@lru_cache
def get_full_backup_dir(repo_root: Path) -> Path:
    # return repo_root / "logs" / "pre-commit" / "full_backup"
    return get_log_dir() / "full_backup"


def get_ratchet_baseline_dir(repo_root: Path) -> Path:
    return get_user_repo_path_from_env() / ".br-pre-commit" / "ratchet"


def get_user_repo_root_from_git(repo_path: str | None = None) -> Path:
    if repo_path:
        return Path(repo_path).resolve()
    result = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
        ).strip()
    )
    return result
