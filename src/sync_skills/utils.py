#!/usr/bin/env python3
"""Compatibility exports for the sync-skill-files utilities."""

from __future__ import annotations

from ..helper.git import GitCommandError, InvalidGitRepositoryError, get_repo
from .core import (
    _BR_PRE_COMMIT_REPO_ROOT,
    _GITHUB_PATH,
    _SKILL_FILENAME,
    AGENTS,
    GIT_COMMIT_SPECIAL,
    HARDCODED_SKIPS,
    RESOLVE_COMMAND,
    _index_bytes,
    _rel,
    _stage,
    classify_skill_path,
    cleanup_empty_skill_dirs,
    discover_skills,
    get_skill_parents,
    is_excluded,
    mirror_slots,
    parse_staged_name_status,
)
from .resolve import interactive_resolve
from .sync import (
    apply_modification,
    compute_intent,
    get_staged_skill_changes,
    remove_mirror,
    remove_skill_from_all_agents,
    verify_sync,
)

__all__ = [
    "AGENTS",
    "GIT_COMMIT_SPECIAL",
    "HARDCODED_SKIPS",
    "_GITHUB_PATH",
    "_BR_PRE_COMMIT_REPO_ROOT",
    "_SKILL_FILENAME",
    "_index_bytes",
    "_rel",
    "_stage",
    "apply_modification",
    "classify_skill_path",
    "cleanup_empty_skill_dirs",
    "compute_intent",
    "discover_skills",
    "get_skill_parents",
    "get_staged_skill_changes",
    "interactive_resolve",
    "is_excluded",
    "mirror_slots",
    "parse_staged_name_status",
    "remove_mirror",
    "remove_skill_from_all_agents",
    "verify_sync",
    "RESOLVE_COMMAND",
    "GitCommandError",
    "InvalidGitRepositoryError",
    "get_repo",
]
