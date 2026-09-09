from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import yaml

PRE_COMMIT_STAGE = "pre-commit"
RATCHET_HOOK_ID = "incremental-ratchet"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "defaults.toml"
PROJECT_CONFIG_NAME = ".br-pre-commit.toml"


def _merged_config(repo_root: Path) -> dict:
    """Load shared defaults, then recursively overlay project settings."""
    defaults = tomllib.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    project_path = repo_root / PROJECT_CONFIG_NAME
    project = tomllib.loads(project_path.read_text(encoding="utf-8")) if project_path.exists() else {}

    def merge(base: dict, override: dict) -> dict:
        result = dict(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = merge(result[key], value)
            else:
                result[key] = value
        return result

    return merge(defaults, project)


@dataclass(frozen=True)
class HookSpec:
    hook_id: str
    mutates_files: bool


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
    }
)


def unknown_hook_policy(repo_root: Path) -> str:
    config = _merged_config(repo_root)
    policy = config["wrapper"]["unknown-hook-policy"]
    if policy not in {"warn", "error"}:
        raise ValueError("wrapper.unknown-hook-policy must be 'warn' or 'error'")
    return policy


def job_timeout_seconds(repo_root: Path) -> float:
    config = _merged_config(repo_root)
    timeout = float(config["wrapper"]["job-timeout-seconds"])
    if timeout <= 0:
        raise ValueError("wrapper.job-timeout-seconds must be positive")
    return timeout


def ratchet_settings(repo_root: Path) -> dict:
    return _merged_config(repo_root)["ratchet"]


def enabled_pre_commit_hook_ids(config_path: Path) -> list[str]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    enabled: list[str] = []
    for repo in config.get("repos", []):
        for hook in repo.get("hooks", []):
            stages = hook.get("stages")
            if stages is None or PRE_COMMIT_STAGE in stages:
                enabled.append(str(hook["id"]))
    return enabled


def classify_hooks(hook_ids: list[str], *, policy: str) -> tuple[list[HookSpec], list[str]]:
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
