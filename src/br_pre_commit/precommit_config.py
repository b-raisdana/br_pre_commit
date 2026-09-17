from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

import yaml

PRE_COMMIT_STAGE = "pre-commit"
RATCHET_HOOK_ID = "incremental-ratchet"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "defaults.toml"
PROJECT_CONFIG_NAME = ".br-pre-commit.toml"


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
    return {**base, **override}


def _merge_ratchet(base: RatchetConfig | None, override: RatchetConfig | None) -> RatchetConfig | None:
    if base is None:
        return override
    if override is None:
        return base
    return {**base, **override}


def _merged_config(repo_root: Path) -> AppConfig:
    """Load shared defaults, then overlay project settings."""
    defaults = cast(AppConfig, tomllib.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")))
    project_path = repo_root / PROJECT_CONFIG_NAME
    project = cast(AppConfig, tomllib.loads(project_path.read_text(encoding="utf-8"))) if project_path.exists() else {}

    result: AppConfig = {}
    wrapper = _merge_wrapper(defaults.get("wrapper"), project.get("wrapper"))
    if wrapper is not None:
        result["wrapper"] = wrapper
    ratchet = _merge_ratchet(defaults.get("ratchet"), project.get("ratchet"))
    if ratchet is not None:
        result["ratchet"] = ratchet
    return result


@dataclass(frozen=True)
class HookSpec:
    hook_id: str
    mutates_files: bool


# Recognized hook IDs the wrapper can classify. Projects must use IDs from
# these sets; see README.md § "Recognized hook IDs" for the full list and
# br_pre_commit/.pre-commit-config.yaml as the authoritative reference config.
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


def unknown_hook_policy(repo_root: Path) -> str:
    config = _merged_config(repo_root)
    wrapper = config.get("wrapper")
    if wrapper is None:
        raise ValueError("wrapper configuration is missing")
    policy = wrapper["unknown-hook-policy"]
    if policy not in {"warn", "error"}:
        raise ValueError("wrapper.unknown-hook-policy must be 'warn' or 'error'")
    return policy


def job_timeout_seconds(repo_root: Path) -> float:
    config = _merged_config(repo_root)
    wrapper = config.get("wrapper")
    if wrapper is None:
        raise ValueError("wrapper configuration is missing")
    timeout = float(wrapper["job-timeout-seconds"])
    if timeout <= 0:
        raise ValueError("wrapper.job-timeout-seconds must be positive")
    return timeout


def protected_branches(repo_root: Path) -> tuple[str, ...]:
    config = _merged_config(repo_root)
    wrapper = config.get("wrapper")
    if wrapper is None:
        raise ValueError("wrapper configuration is missing")
    branches = wrapper.get("protected-branches", [])
    if not isinstance(branches, list) or any(not isinstance(branch, str) or not branch for branch in branches):
        raise ValueError("wrapper.protected-branches must be a list of non-empty strings")
    return tuple(branches)


def ratchet_settings(repo_root: Path) -> RatchetConfig:
    config = _merged_config(repo_root)
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
    Projects must use IDs from those sets — see ``br_pre_commit/.pre-commit-config.yaml``
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
