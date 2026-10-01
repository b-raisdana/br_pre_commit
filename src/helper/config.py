import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic_settings import BaseSettings

from .paths import get_pyproject_toml_path


class FromPyProjectTomlConfig(BaseSettings):
    @classmethod
    @lru_cache
    def from_pyproject_toml(cls, section: str, pyproject_toml_path: Path | None = None) -> Self:
        pyproject_toml_path = pyproject_toml_path or get_pyproject_toml_path()
        with pyproject_toml_path.open("rb") as file:
            data = tomllib.load(file)

        return cls.model_validate(data.get("tool", {}).get("br_pre_commit", {}).get(section, {}))
