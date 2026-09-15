#!/usr/bin/env python3
"""Compatibility exports for the sync-skill-files utilities."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from git import Repo  # noqa: E402
from sync_skill_core import (  # noqa: E402
    _GITHUB_PATH,
    _REPO_ROOT,
    _SKILL_FILENAME,
    AGENTS,
    GIT_COMMIT_SPECIAL,
    HARDCODED_SKIPS,
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
from sync_skill_sync import (  # noqa: E402
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
    "_REPO_ROOT",
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
    "is_excluded",
    "mirror_slots",
    "parse_staged_name_status",
    "remove_mirror",
    "remove_skill_from_all_agents",
    "verify_sync",
    "Repo",
]
