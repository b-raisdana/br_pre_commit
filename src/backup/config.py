from ..helper.config import FromPyProjectTomlConfig


class BackupConfig(FromPyProjectTomlConfig):
    staged_prefix: str = "staged"
    unstaged_prefix: str = "unstaged"
    untracked_prefix: str = "untracked"

    full_backup_exclude_dir_regex: str = r"^(data|logs|archive_not_used_trash|\.[^/]+)$"


backup_config = BackupConfig.from_pyproject_toml("backup")
