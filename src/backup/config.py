from pydantic_settings import SettingsConfigDict

from ..helper.config import FromPyProjectTomlConfig
from ..helper.paths import get_br_pre_commit_repo_path_from_env


class BackupConfig(FromPyProjectTomlConfig):  # type: ignore[misc]
    model_config = SettingsConfigDict(populate_by_name=True, extra="allow")
    staged_prefix: str = "staged"
    unstaged_prefix: str = "unstaged"
    untracked_prefix: str = "untracked"

    full_backup_exclude_dir_regex: str = r"^(data|logs|archive_not_used_trash|\.[^/]+)$"


_br_pre_commit_repo_root = get_br_pre_commit_repo_path_from_env()
_pyproject_toml_path = _br_pre_commit_repo_root / "pyproject.toml"

backup_config = BackupConfig.from_pyproject_toml("backup", pyproject_toml_path=_pyproject_toml_path)
