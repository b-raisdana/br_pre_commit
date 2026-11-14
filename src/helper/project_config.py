"""Merge shared br_pre_commit defaults into a consuming project's pyproject."""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path

from .paths import get_pyproject_toml_path

type ProjectConfigValue = str | int | list[str]

PROJECT_CONFIG_DEFAULTS: dict[str, dict[str, ProjectConfigValue]] = {
    "wrapper": {
        "read-only-hooks": [],
        "mutating-hooks": [],
        "unknown-hook-policy": "warn",
        "job-timeout-seconds": 180,
        "protected-branches-regex": "^(main|develop|uat)$",
        "pre_commit_stage": "pre-commit",
    },
    "ratchet": {
        "target": "src",
        "max-lines": 300,
        "line-growth-slack": 5,
        "complexity-ranks": "ABCDEF",
        "xenon-max-absolute": "B",
        "ratchet_data_folder_rel_path": "ratchet",
        "baseline_glob": "baseline*.json",
        "mypy_coded_error_re": r": error: .*\[([\w-]+)\]\s*$",
        "mypy_uncoded_error_re": ": error: ",
        "exclude-dir": "archive_not_used_trash",
        "exclude_dirs": ["archive_not_used_trash"],
    },
}


def _toml_value(value: ProjectConfigValue) -> str:
    """Serialize the scalar/list values used by the shared project defaults."""
    if isinstance(value, list):
        if not value:
            return "[]"
        serialized_items = ",\n".join(f"    {json.dumps(item, ensure_ascii=False)}" for item in value)
        return "[\n" + serialized_items + "\n]"
    return json.dumps(value, ensure_ascii=False)


def _merge_defaults(contents: str) -> tuple[str, list[str]]:
    """Add absent shared settings while preserving every project-specific value."""
    parsed = tomllib.loads(contents)
    br_config = parsed.get("tool", {}).get("br_pre_commit", {})
    messages: list[str] = []

    for section, defaults in PROJECT_CONFIG_DEFAULTS.items():
        existing = br_config.get(section, {})
        missing = [(key, value) for key, value in defaults.items() if key not in existing]
        if not missing:
            continue

        header = f"[tool.br_pre_commit.{section}]"
        header_match = re.search(rf"(?m)^{re.escape(header)}\s*$", contents)
        additions = [f"{key} = {_toml_value(value)}" for key, value in missing]
        if header_match is None:
            contents = contents.rstrip() + f"\n\n{header}\n" + "\n".join(additions) + "\n"
        else:
            next_header = re.search(r"(?m)^\[", contents[header_match.end() :])
            insert_at = header_match.end() + next_header.start() if next_header else len(contents)
            before = contents[:insert_at].rstrip("\r\n")
            after = contents[insert_at:].lstrip("\r\n")
            contents = before + "\n" + "\n".join(additions) + ("\n\n" + after if after else "\n")
        messages.append(f"Added missing defaults to {header}: {', '.join(key for key, _ in missing)}")
        parsed = tomllib.loads(contents)
        br_config = parsed.get("tool", {}).get("br_pre_commit", {})

    return contents, messages


def _merge_wrapper_hook_classifications(
    contents: str,
    shared_wrapper: Mapping[str, ProjectConfigValue],
) -> tuple[str, bool]:
    """Register shared hook IDs while preserving project-specific classifications."""
    parsed = tomllib.loads(contents)
    wrapper = parsed.get("tool", {}).get("br_pre_commit", {}).get("wrapper", {})
    changed = False

    for key in ("mutating-hooks", "read-only-hooks"):
        shared_hooks = shared_wrapper.get(key, [])
        current_hooks = wrapper.get(key, [])
        if not isinstance(shared_hooks, list) or not isinstance(current_hooks, list):
            continue
        additions = [hook_id for hook_id in shared_hooks if isinstance(hook_id, str) and hook_id not in current_hooks]
        if not additions:
            continue

        merged_hooks = [*current_hooks, *additions]
        field_pattern = re.compile(rf"(?ms)^{re.escape(key)}\s*=\s*\[[^\]]*\]")
        replacement = f"{key} = {_toml_value(merged_hooks)}"
        if field_pattern.search(contents):
            contents = field_pattern.sub(replacement, contents, count=1)
        else:
            table_header = "[tool.br_pre_commit.wrapper]"
            header_match = re.search(rf"(?m)^{re.escape(table_header)}\s*$", contents)
            if header_match is None:
                contents = contents.rstrip() + f"\n\n{table_header}\n{replacement}\n"
            else:
                next_header = re.search(r"(?m)^\[", contents[header_match.end() :])
                insert_at = header_match.end() + next_header.start() if next_header else len(contents)
                contents = (
                    contents[:insert_at].rstrip("\r\n") + f"\n{replacement}\n\n" + contents[insert_at:].lstrip("\r\n")
                )
        changed = True
        parsed = tomllib.loads(contents)
        wrapper = parsed.get("tool", {}).get("br_pre_commit", {}).get("wrapper", {})

    return contents, changed


def merge_project_pyproject_config(
    user_repo_root: Path,
    br_pre_commit_repo_root: Path | None = None,
) -> list[str]:
    """Merge shared wrapper/ratchet defaults and hook classifications into pyproject.toml."""
    config_path = get_pyproject_toml_path()
    if not config_path.exists():
        config_path.write_text("", encoding="utf-8")
    original = config_path.read_text(encoding="utf-8")
    updated, messages = _merge_defaults(original)
    if br_pre_commit_repo_root is not None:
        source_path = br_pre_commit_repo_root / "pyproject.toml"
        source = tomllib.loads(source_path.read_text(encoding="utf-8"))
        shared_wrapper = source.get("tool", {}).get("br_pre_commit", {}).get("wrapper", {})
        updated, classifications_changed = _merge_wrapper_hook_classifications(updated, shared_wrapper)
        if classifications_changed:
            messages.append("Registered shared br_pre_commit hook classifications")
    if updated != original:
        config_path.write_text(updated, encoding="utf-8", newline="\n")
        messages.insert(0, f"Updated {config_path.relative_to(user_repo_root)}")
    return messages
