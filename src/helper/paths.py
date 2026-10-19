import os
from functools import lru_cache
from pathlib import Path

_GIT_REPOSITORY_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_PREFIX",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def git_subprocess_env(*, inherit_index: bool = True) -> dict[str, str]:
    """Remove hook worktree overrides while preserving its active index by default."""
    env = os.environ.copy()
    for name in _GIT_REPOSITORY_ENV:
        env.pop(name, None)
    if not inherit_index:
        env.pop("GIT_INDEX_FILE", None)
    return env


@lru_cache
def get_user_repo_path_from_env() -> Path:
    from ..config import br_pre_commit_config

    user_repo_root = br_pre_commit_config.user_repo_root
    if not user_repo_root:
        raise ValueError("USER_REPO_ROOT environment variable is required")
    return Path(user_repo_root).resolve()


@lru_cache
def get_br_pre_commit_repo_path_from_env() -> Path:
    from ..config import br_pre_commit_config

    br_pre_commit_repo_root = br_pre_commit_config.br_pre_commit_repo_root
    if not br_pre_commit_repo_root:
        raise ValueError("BR_PRE_COMMIT_REPO_ROOT environment variable is required")
    return Path(br_pre_commit_repo_root).resolve()


@lru_cache
def get_br_pre_commit_package_prefix(user_repo_root: Path, br_pre_commit_repo_root: Path) -> str:
    """Dotted prefix under which this repository's ``src`` package is importable.

    A consuming repository holds br_pre_commit as a submodule, so its entry points
    are reached as ``br_pre_commit.src.<module>``. When br_pre_commit is the
    repository being hooked itself, ``src.<module>`` is the only importable form,
    because there is no enclosing ``br_pre_commit`` package to import from.
    """
    return "src" if user_repo_root.resolve() == br_pre_commit_repo_root.resolve() else "br_pre_commit.src"


@lru_cache
def get_br_pre_commit_package_prefix_from_env() -> str:
    return get_br_pre_commit_package_prefix(
        get_user_repo_path_from_env(),
        get_br_pre_commit_repo_path_from_env(),
    )


@lru_cache
def get_log_dir() -> Path:
    from .config import log_config

    return get_user_repo_path_from_env() / log_config.log_dir_rel_path


@lru_cache
def get_log_file() -> Path:
    return get_log_dir() / "pre-commit"


@lru_cache
def get_pre_commit_config_yaml_path() -> Path:
    from ..config import br_pre_commit_config

    return get_user_repo_path_from_env() / br_pre_commit_config.pre_commit_config_yaml_file_name


@lru_cache
def get_pyproject_toml_path() -> Path:
    from ..config import br_pre_commit_config

    return get_user_repo_path_from_env() / br_pre_commit_config.py_project_toml_file_name  # "pyproject.toml"


@lru_cache
def get_full_backup_dir() -> Path:
    return get_log_dir() / "full_backup"


def get_backup_manifest_dir() -> Path:
    """Directory where per-attempt backup manifests live.

    Each pre-commit/backup attempt writes a single JSON manifest here whose
    name is the human-readable timestamp (with milliseconds) of the attempt.
    """
    dir_ = get_log_dir() / "backup-manifests"
    dir_.mkdir(parents=True, exist_ok=True)
    return dir_


def get_ratchet_baseline_dir() -> Path:
    dir_ = get_user_repo_path_from_env() / ".br-pre-commit" / "ratchet"
    dir_.mkdir(parents=True, exist_ok=True)
    return dir_


def get_user_repo_root_from_git(repo_path: str | None = None) -> Path:
    if repo_path:
        return Path(repo_path).resolve()
    from .git import run_git

    result = run_git("rev-parse", "--show-toplevel", git_repo_root=Path.cwd())
    return Path(result.stdout.strip())
