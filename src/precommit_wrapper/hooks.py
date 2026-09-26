from dataclasses import dataclass
from pathlib import Path

from precommit_wrapper.config import get_mutating_hooks


def enabled_pre_commit_hook_ids(config_path: Path | None = None) -> list[str]:
    from precommit_wrapper.config import get_pre_commit_config_from_yaml, wrapper_config

    config = get_pre_commit_config_from_yaml(config_path)
    enabled: list[str] = []
    for repo in config.get("repos", []):
        for hook in repo.get("hooks", []):
            if isinstance(hook, str):
                hook_id = hook
                stages = None
            else:
                hook_id = hook.get("id")
                stages = hook.get("stages")
            if not isinstance(hook_id, str) or not hook_id:
                continue
            if stages is None or wrapper_config.pre_commit_stage in stages:
                enabled.append(hook_id)
    return enabled


def pre_commit_hook_is_enabled(hook_id: str, config_path: Path | None = None) -> bool:
    """Return whether a hook's master switch enables it for normal commits."""
    return hook_id in enabled_pre_commit_hook_ids(config_path)


@dataclass(frozen=True)
class HookSpec:
    hook_id: str
    mutates_files: bool


# Recognized hook IDs the wrapper can classify. Projects must use IDs from
# these sets; see README.md § "Recognized hook IDs" for the full list and
# .pre-commit-config.yaml as the authoritative reference config.
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
        # if hook_id in _MUTATING_HOOKS:
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
