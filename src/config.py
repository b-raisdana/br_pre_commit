from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    br_pre_commit_repo_root: str = Field(validation_alias="BR_PRE_COMMIT_REPO_ROOT")
    user_repo_root: str = Field(validation_alias="USER_REPO_ROOT")

    data_folder_rel_path: Path = Path(".br-pre-commit")
    py_project_toml_file_name: Path = Path("pyproject.toml")
    pre_commit_config_yaml_file_name: Path = Path(".pre-commit-config.yaml")

    ratchet_hook_id: str = "incremental-ratchet"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


br_pre_commit_config = AppConfig()
