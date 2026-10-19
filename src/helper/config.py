import logging
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, ValidationError
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict

from .paths import get_pyproject_toml_path

logger = logging.getLogger(__name__)


class FromPyProjectTomlConfig(BaseSettings):  # type: ignore[explicit-any]
    model_config = SettingsConfigDict(extra="allow", populate_by_name=True)

    @classmethod
    @lru_cache
    def from_pyproject_toml(cls, section: str, pyproject_toml_path: Path | None = None) -> Self:
        pyproject_toml_path = pyproject_toml_path or get_pyproject_toml_path()
        with pyproject_toml_path.open("rb") as file:
            data = tomllib.load(file)

        raw_section = data.get("tool", {}).get("br_pre_commit", {}).get(section, {})
        if not isinstance(raw_section, dict):
            logger.warning("Config section '%s' is not a dict, using defaults", section)
            raw_section = {}

        field_keys: dict[str, set[str]] = {}
        for _field_name, field_info in cls.model_fields.items():
            keys = {_field_name}
            if isinstance(field_info, FieldInfo):
                validation_alias = field_info.validation_alias
                if isinstance(validation_alias, str):
                    keys.add(validation_alias)
                elif isinstance(validation_alias, (list, tuple)):
                    keys.update(str(a) for a in validation_alias)
            field_keys[_field_name] = keys

        known_keys = set().union(*field_keys.values()) if field_keys else set()
        raw_keys = set(raw_section.keys())
        extra_keys = raw_keys - known_keys
        missing_keys = {name for name, keys in field_keys.items() if not keys & raw_keys}

        if extra_keys:
            logger.warning("Config section '%s': extra keys will be ignored: %s", section, sorted(extra_keys))
        if missing_keys:
            logger.warning(
                "Config section '%s': missing keys use defaults: %s; override them in %s [tool.br_pre_commit.%s]",
                section,
                sorted(missing_keys),
                pyproject_toml_path,
                section,
            )

        try:
            return cls.model_validate(raw_section)
        except ValidationError as exc:
            logger.error("Config section '%s' validation failed, using defaults: %s", section, exc)
            return cls()


class LogConfig(FromPyProjectTomlConfig):
    model_config = SettingsConfigDict(populate_by_name=True, extra="allow")

    log_dir_rel_path: Path = Field(default=Path("logs/pre-commit"), validation_alias="log-dir")


log_config = LogConfig.from_pyproject_toml("log")
