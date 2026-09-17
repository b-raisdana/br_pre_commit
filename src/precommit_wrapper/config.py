from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

import yaml

PRE_COMMIT_STAGE = "pre-commit"
RATCHET_HOOK_ID = "incremental-ratchet"
PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _read_toml_section(path: Path, section: str) -> dict[str, object]:  # ignore: no-object-annotations
    """Read a top-level section from a TOML file, returning {} on any error."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    value = data.get(section)
    if not isinstance(value, dict):
        return {}
    return cast("dict[str, object]", value)  # ignore: no-object-annotations


def _shared_defaults() -> dict[str, dict[str, object]]:  # ignore: no-object-annotations
    """Read shared defaults from [tool.br_pre_commit.*] in pyproject.toml."""
    tool = _read_toml_section(PYPROJECT_PATH, "tool")
    return cast("dict[str, dict[str, object]]", tool.get("br_pre_commit", {}))  # ignore: no-object-annotations


def _flatten_defaults() -> dict[str, dict[str, object]]:  # ignore: no-object-annotations
    """Map [tool.br_pre_commit.<name>] sections onto flat [name] sections."""
    return _shared_defaults()


WrapperConfig = TypedDict(
    "WrapperConfig", {"unknown-hook-policy": str, "job-timeout-seconds": float, "protected-branches": list[str]}
)
RatchetConfig = TypedDict(
    "RatchetConfig",
    {
        "target": str,
        "max-lines": int,
        "line-growth-slack": int,
        "complexity-ranks": str,
        "xenon-max-absolute": str,
        "exclude-dir": str,
    },
    total=False,
)


class AppConfig(TypedDict, total=False):
    wrapper: WrapperConfig
    ratchet: RatchetConfig


class PreCommitHook(TypedDict, total=False):
    id: str
    stages: list[str]


class PreCommitRepo(TypedDict, total=False):
    hooks: list[PreCommitHook]


class PreCommitConfig(TypedDict, total=False):
    repos: list[PreCommitRepo]


def _merge_wrapper(base: WrapperConfig | None, override: WrapperConfig | None) -> WrapperConfig | None:
    if base is None:
        return override
    if override is None:
        return base
    return WrapperConfig(**base, **override)


def _merge_ratchet(base: RatchetConfig | None, override: RatchetConfig | None) -> RatchetConfig | None:
    if base is None:
        return override
    if override is None:
        return base
    return RatchetConfig(**base, **override)


def _merged_config() -> AppConfig:
    """Load shared defaults from [tool.br_pre_commit.*] in pyproject.toml."""
    defaults = _flatten_defaults()
    result = AppConfig(**defaults)
    return result


@dataclass(frozen=True)
class HookSpec:
    hook_id: str
    mutates_files: bool


# Recognized hook IDs the wrapper can classify. Projects must use IDs from
# these sets; see README.md § "Recognized hook IDs" for the full list and
# .pre-commit-config.yaml as the authoritative reference config.
_MUTATING_HOOKS = frozenset(
    {
        "trailing-whitespace",
        "end-of-file-fixer",
        "mixed-line-ending",
        "ruff",
        "ruff-format",
        "sync-skill-files",
    }
)
_READ_ONLY_HOOKS = frozenset(
    {
        "check-yaml",
        "check-toml",
        "check-added-large-files",
        "check-merge-conflict",
        "check-case-conflict",
        "debug-statements",
        RATCHET_HOOK_ID,
        "pytest-fast",
        "pytest-integration-collect",
        "integration-tests",
        "check-pandera-decorator",
        "no-commit-to-main",
        "no-object-annotations",
    }
)


def unknown_hook_policy() -> str:
    config = _merged_config()
    wrapper = config.get("wrapper")
    if wrapper is None:
        raise ValueError("wrapper configuration is missing")
    policy = wrapper["unknown-hook-policy"]
    if policy not in {"warn", "error"}:
        raise ValueError("wrapper.unknown-hook-policy must be 'warn' or 'error'")
    return policy


def job_timeout_seconds() -> float:
    config = _merged_config()
    wrapper = config.get("wrapper")
    if wrapper is None:
        raise ValueError("wrapper configuration is missing")
    timeout = float(wrapper["job-timeout-seconds"])
    if timeout <= 0:
        raise ValueError("wrapper.job-timeout-seconds must be positive")
    return timeout


def protected_branches() -> tuple[str, ...]:
    config = _merged_config()
    wrapper = config.get("wrapper")
    if wrapper is None:
        raise ValueError("wrapper configuration is missing")
    branches = wrapper.get("protected-branches", [])
    if not isinstance(branches, list) or any(not isinstance(branch, str) or not branch for branch in branches):
        raise ValueError("wrapper.protected-branches must be a list of non-empty strings")
    return tuple(branches)


def ratchet_settings() -> RatchetConfig:
    config = _merged_config()
    settings = config.get("ratchet")
    if settings is None:
        raise ValueError("ratchet configuration is missing")
    return settings


def enabled_pre_commit_hook_ids(config_path: Path) -> list[str]:
    config = cast(PreCommitConfig, yaml.safe_load(config_path.read_text(encoding="utf-8")) or {})
    enabled: list[str] = []
    for repo in config.get("repos", []):
        for hook in repo.get("hooks", []):
            hook_id = hook.get("id")
            if not isinstance(hook_id, str) or not hook_id:
                continue
            stages = hook.get("stages")
            if stages is None or PRE_COMMIT_STAGE in stages:
                enabled.append(hook_id)
    return enabled


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
        if hook_id in _MUTATING_HOOKS:
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
