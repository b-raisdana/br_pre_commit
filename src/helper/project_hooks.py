"""Install the shared hook definitions into a consuming project."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import yaml

from ..precommit_wrapper.config import PreCommitConfig, PreCommitHook, PreCommitRepo
from .paths import get_br_pre_commit_package_prefix, get_pre_commit_config_yaml_path


def _project_hook_templates(tool_root: Path) -> PreCommitConfig:
    config_path = tool_root / ".pre-commit-config.yaml"
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return cast(PreCommitConfig, loaded if isinstance(loaded, dict) else {"repos": []})


def _consumer_hook(hook: PreCommitHook, consumer_root: Path, tool_root: Path) -> PreCommitHook:
    entry = hook.get("entry")
    if isinstance(entry, str) and entry.startswith("python -m src."):
        prefix = get_br_pre_commit_package_prefix(consumer_root, tool_root)
        return cast(PreCommitHook, {**hook, "entry": entry.replace("python -m src.", f"python -m {prefix}.", 1)})
    return dict(hook)


def _has_python_tests(repo_root: Path) -> bool:
    tests_root = repo_root / "tests"
    return tests_root.is_dir() and any(tests_root.rglob("test_*.py"))


def _merge_hook(target: list[PreCommitHook], template: PreCommitHook) -> bool:
    hook_id = template.get("id")
    if not isinstance(hook_id, str):
        return False
    existing = next((hook for hook in target if hook.get("id") == hook_id), None)
    if existing is None:
        target.append(dict(template))
        return True
    missing = {key: value for key, value in template.items() if key not in existing}
    existing.update(missing)
    return bool(missing)


def _merge_repos(config: PreCommitConfig, consumer_root: Path, tool_root: Path) -> list[str]:
    messages: list[str] = []
    repos = config.setdefault("repos", [])
    has_tests = _has_python_tests(consumer_root)
    for template_repo in _project_hook_templates(tool_root).get("repos", []):
        repo_name = template_repo.get("repo")
        if not isinstance(repo_name, str):
            continue
        rev = template_repo.get("rev")
        target_repo: PreCommitRepo | None = next(
            (repo for repo in repos if repo.get("repo") == repo_name and repo.get("rev") == rev), None
        )
        if target_repo is None:
            target_repo = cast(PreCommitRepo, {key: value for key, value in template_repo.items() if key != "hooks"})
            target_repo["hooks"] = []
            repos.append(target_repo)
        hook_ids = [
            hook_id
            for hook in template_repo.get("hooks", [])
            if (hook_id := hook.get("id")) != "pytest-fast" or has_tests
            if _merge_hook(target_repo.setdefault("hooks", []), _consumer_hook(hook, consumer_root, tool_root))
        ]
        valid_ids = [hook_id for hook_id in hook_ids if isinstance(hook_id, str)]
        if valid_ids:
            messages.append(f"Added/completed hooks in {repo_name}: {', '.join(valid_ids)}")
    return messages


def merge_project_config(consumer_root: Path, tool_root: Path) -> list[str]:
    """Merge shared hooks into a consumer config, retaining project-specific hooks."""
    config_path = get_pre_commit_config_yaml_path()
    messages: list[str] = []
    if not config_path.exists():
        config_path.write_text("repos:\n", encoding="utf-8")
        messages.append(f"Created {config_path.relative_to(consumer_root)}")

    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config = cast(PreCommitConfig, loaded if isinstance(loaded, dict) else {"repos": []})
    if not isinstance(config.get("repos"), list):
        config["repos"] = []
    messages.extend(_merge_repos(config, consumer_root, tool_root))
    config_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False), encoding="utf-8")
    return messages
