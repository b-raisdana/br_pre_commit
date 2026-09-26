from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict, cast

import yaml
from pydantic import Field, field_validator

from helper.config import FromPyProjectTomlConfig

# def _flatten_defaults() -> dict[str, dict[str, object]]:  # ignore: no-object-annotations
#     """Map [tool.br_pre_commit.<name>] sections onto flat [name] sections."""
#     return _shared_defaults()


# WrapperConfig = TypedDict(
#     "WrapperConfig", {"unknown-hook-policy": str, "job-timeout-seconds": float, "protected-branches": list[str]}
# )


class WrapperConfig(FromPyProjectTomlConfig):
    protected_branches: list[str] = Field(default=[], validation_alias="protected-branches")
    unknown_hook_policy: Literal["warn", "error"] = Field(default="warn", validation_alias="unknown-hook-policy")
    job_timeout_seconds: int = Field(default=3 * 60, validation_alias="job-timeout-seconds")

    @field_validator("protected_branches", mode="before")
    @classmethod
    def _validate_protected_branches(cls, value: list[str]) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(branch, str) or not branch for branch in value):
            raise ValueError("wrapper.protected-branches must be a list of non-empty strings")
        return value

    # PRE_COMMIT_STAGE = "pre-commit"
    # RATCHET_HOOK_ID = "incremental-ratchet"
    # TOOL_ROOT = Path(__file__).resolve().parents[1]
    pre_commit_stage: str = "pre-commit"


wrapper_config = WrapperConfig.from_pyproject_toml("wrapper")


# class AppConfig(TypedDict, total=False):
#     wrapper: WrapperConfig
#     ratchet: RatchetConfig


class PreCommitHook(TypedDict, total=False):
    id: str
    stages: list[str]


class PreCommitRepo(TypedDict, total=False):
    hooks: list[PreCommitHook]


class PreCommitConfig(TypedDict, total=False):
    repos: list[PreCommitRepo]


def get_pre_commit_config_from_yaml(config_path: Path | None = None) -> PreCommitConfig:
    from config import br_pre_commit_config

    config_path = config_path or br_pre_commit_config.pre_commit_config_yaml_file_name
    config = cast(PreCommitConfig, yaml.safe_load(config_path.read_text(encoding="utf-8")) or {})
    return config


@dataclass(frozen=True)
class HookSpec:
    hook_id: str
    mutates_files: bool


# Recognized hook IDs the wrapper can classify. Projects must use IDs from
# these sets; see README.md § "Recognized hook IDs" for the full list and
# .pre-commit-config.yaml as the authoritative reference config.
def get_mutating_hooks() -> frozenset[str]:
    from config import br_pre_commit_config

    return frozenset(
        {
            "trailing-whitespace",
            "end-of-file-fixer",
            "mixed-line-ending",
            "ruff",
            "ruff-format",
            "sync-skill-files",
            br_pre_commit_config.ratchet_hook_id,
        }
    )


# _MUTATING_HOOKS = frozenset(
#     {
#         "trailing-whitespace",
#         "end-of-file-fixer",
#         "mixed-line-ending",
#         "ruff",
#         "ruff-format",
#         "sync-skill-files",
#         br_pre_commit_config.ratchet_hook_id,
#     }
# )
_READ_ONLY_HOOKS = frozenset(
    {
        "check-yaml",
        "check-toml",
        "check-added-large-files",
        "check-merge-conflict",
        "check-case-conflict",
        "debug-statements",
        "pytest-fast",
        "pytest-integration-collect",
        "integration-tests",
        "check-pandera-decorator",
        "no-commit-to-main",
        "no-object-annotations",
    }
)


# def unknown_hook_policy() -> str:
#     config = _merged_config()
#     wrapper = config.get("wrapper")
#     if wrapper is None:
#         raise ValueError("wrapper configuration is missing")
#     policy = wrapper["unknown-hook-policy"]
#     if policy not in {"warn", "error"}:
#         raise ValueError("wrapper.unknown-hook-policy must be 'warn' or 'error'")
#     return policy


# def job_timeout_seconds() -> float:
#     config = _merged_config()
#     wrapper = config.get("wrapper")
#     if wrapper is None:
#         raise ValueError("wrapper configuration is missing")
#     timeout = float(wrapper["job-timeout-seconds"])
#     if timeout <= 0:
#         raise ValueError("wrapper.job-timeout-seconds must be positive")
#     return timeout


# def protected_branches() -> tuple[str, ...]:
#     config = _merged_config()
#     wrapper = config.get("wrapper")
#     if wrapper is None:
#         raise ValueError("wrapper configuration is missing")
#     branches = wrapper.get("protected-branches", [])
#     if not isinstance(branches, list) or any(not isinstance(branch, str) or not branch for branch in branches):
#         raise ValueError("wrapper.protected-branches must be a list of non-empty strings")
#     return tuple(branches)


# def ratchet_settings() -> RatchetConfig:
#     config = _merged_config()
#     settings = config.get("ratchet")
#     if settings is None:
#         raise ValueError("ratchet configuration is missing")
#     return settings


def classify_hooks(hook_ids: list[str], *, policy: str) -> tuple[list[HookSpec], list[str]]:
    """Classify hook IDs into mutating (serial) and read-only (concurrent) specs.

    Hook IDs not in ``_MUTATING_HOOKS`` or ``_READ_ONLY_HOOKS`` are "unknown".
    With ``policy="error"`` they raise ``ValueError``; with ``"warn"`` they
    run serially. See README.md § "Recognized hook IDs" for the full list.
    Projects must use IDs from those sets — see ``.pre-commit-config.yaml``
    as the authoritative reference.
    """
    specs: list[HookSpec] = []
    unknown: list[str] = []
    for hook_id in hook_ids:
        if hook_id in get_mutating_hooks():
            specs.append(HookSpec(hook_id, mutates_files=True))
        elif hook_id in _READ_ONLY_HOOKS:
            specs.append(HookSpec(hook_id, mutates_files=False))
        else:
            unknown.append(hook_id)
            if policy == "warn":
                specs.append(HookSpec(hook_id, mutates_files=True))
    if unknown and policy == "error":
        raise ValueError(f"unregistered pre-commit hook(s): {', '.join(unknown)}")
    return specs, unknown
