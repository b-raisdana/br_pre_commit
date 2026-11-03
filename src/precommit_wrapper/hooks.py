from pathlib import Path


def enabled_pre_commit_hook_ids(config_path: Path | None = None) -> list[str]:
    from .config import get_pre_commit_config_from_yaml, wrapper_config

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
