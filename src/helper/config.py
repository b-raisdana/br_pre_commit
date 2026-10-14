import logging
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import ConfigDict, ValidationError
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings

from .paths import get_pyproject_toml_path

logger = logging.getLogger(__name__)


class FromPyProjectTomlConfig(BaseSettings):  # type: ignore[explicit-any]
    model_config = ConfigDict(extra="allow", populate_by_name=True)

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

        model_fields = set(cls.model_fields.keys())
        alias_keys = set()
        for _field_name, field_info in cls.model_fields.items():
            if isinstance(field_info, FieldInfo):
                validation_alias = field_info.validation_alias
                if isinstance(validation_alias, str):
                    alias_keys.add(validation_alias)
                elif isinstance(validation_alias, (list, tuple)):
                    alias_keys.update(str(a) for a in validation_alias)

        known_keys = model_fields | alias_keys
        raw_keys = set(raw_section.keys())
        extra_keys = raw_keys - known_keys
        missing_keys = model_fields - raw_keys

        if extra_keys:
            logger.warning("Config section '%s': extra keys will be ignored: %s", section, sorted(extra_keys))
        if missing_keys:
            logger.info("Config section '%s': missing keys will use defaults: %s", section, sorted(missing_keys))

        try:
            return cls.model_validate(raw_section)
        except ValidationError as exc:
            logger.error("Config section '%s' validation failed, using defaults: %s", section, exc)
            return cls()
