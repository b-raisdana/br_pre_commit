import logging
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Self

from pydantic_settings import BaseSettings, SettingsConfigDict

from .paths import get_pyproject_toml_path

log = logging.getLogger("br_pre_commit.config")


class FromPyProjectTomlConfig(BaseSettings):  # type: ignore[explicit-any]
    """Base for configs loaded from ``[tool.br_pre_commit.<section>]``.

    Schema mismatches (extra or missing keys) are reported as errors and the
    offending extra keys are dropped so a single bad key never aborts the whole
    pre-commit run; configured defaults fill in the gaps.
    """

    model_config = SettingsConfigDict(populate_by_name=True, extra="forbid")

    @classmethod
    def _expected_input_keys(cls) -> set[str]:
        keys: set[str] = set()
        for name, field in cls.model_fields.items():
            keys.add(name)
            alias = field.validation_alias or field.alias
            if isinstance(alias, str):
                keys.add(alias)
        return keys

    @classmethod
    def _report_schema_issues(cls, section: str, data: dict[str, Any], source: Path) -> dict[str, Any]:
        expected = cls._expected_input_keys()
        extras = sorted(k for k in data if k not in expected)
        missing = sorted(
            name
            for name, field in cls.model_fields.items()
            if field.is_required() and name not in data and (field.validation_alias or field.alias) not in data
        )
        if extras:
            log.error(
                "config schema mismatch in %s [%s]: unknown key(s) %s (expected: %s)",
                source,
                section,
                ", ".join(extras),
                ", ".join(sorted(expected)),
            )
        if missing:
            log.error(
                "config schema mismatch in %s [%s]: missing required key(s) %s",
                source,
                section,
                ", ".join(missing),
            )
        # Drop extras so validation succeeds; required-missing fields fall back
        # to their declared defaults rather than aborting the run.
        return {k: v for k, v in data.items() if k in expected}

    @classmethod
    @lru_cache
    def from_pyproject_toml(cls, section: str, pyproject_toml_path: Path | None = None) -> Self:
        pyproject_toml_path = pyproject_toml_path or get_pyproject_toml_path()
        with pyproject_toml_path.open("rb") as file:
            data = tomllib.load(file)

        section_data = data.get("tool", {}).get("br_pre_commit", {}).get(section, {})
        if not isinstance(section_data, dict):
            log.error(
                "config schema mismatch in %s [%s]: section must be a table, got %s",
                pyproject_toml_path,
                section,
                type(section_data).__name__,
            )
            section_data = {}
        cleaned = cls._report_schema_issues(section, section_data, pyproject_toml_path)
        return cls.model_validate(cleaned)
