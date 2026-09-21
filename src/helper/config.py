import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic_settings import BaseSettings

from helper.paths import get_pyproject_toml_path

# def read_toml_section(section: str, path: Path | None = None) -> dict[str, object]:  # ignore: no-object-annotations
#     """Read a top-level section from a TOML file, returning {} on any error."""
#     if path is None:
#         path = get_pyproject_toml_path()
#     try:
#         data = tomllib.loads(path.read_text(encoding="utf-8"))
#     except Exception:
#         return {}
#     value = data.get(section)
#     if not isinstance(value, dict):
#         return {}
#     return cast("dict[str, object]", value)  # ignore: no-object-annotations
#
#
# def get_tool_pyproject_toml_settings() -> dict[str, dict[str, object]]:  # ignore: no-object-annotations
#     """Read shared defaults from [tool.br_pre_commit.*] in pyproject.toml."""
#     tool = read_toml_section("tool")
#     return cast("dict[str, dict[str, object]]", tool.get("br_pre_commit", {}))  # ignore: no-object-annotations


class FromPyProjectTomlConfig(BaseSettings):
    @classmethod
    @lru_cache
    def from_pyproject_toml(cls, section: str, pyproject_toml_path: Path | None = None) -> Self:
        pyproject_toml_path = pyproject_toml_path or get_pyproject_toml_path()
        with pyproject_toml_path.open("rb") as file:
            data = tomllib.load(file)

        return cls.model_validate(data.get("tool", {}).get("br_pre_commit", {}).get(section, {}))
