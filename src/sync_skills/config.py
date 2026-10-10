from __future__ import annotations

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from ..helper.config import FromPyProjectTomlConfig


class SyncSkillsConfig(FromPyProjectTomlConfig):
    model_config = SettingsConfigDict(populate_by_name=True)

    hardcoded_skips: list[str] = Field(
        default=["use-aget-skills", "kilo-only-todo-discipline"], validation_alias="hardcoded-skips"
    )


sync_skills_config = SyncSkillsConfig.from_pyproject_toml("sync_skills")
