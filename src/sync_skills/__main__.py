#!/usr/bin/env python3
"""Sync mirrored SKILL.md across agent directories.

Mirrors: .claude/skills, .codex/skills, .devin/skills, .qoder/skills,
.copilot/skills, .kiro/skills, .kilo/skills (and .github/git-commit for
git-commit skill only).

Detection: git staged state only (git diff --cached --name-status). This
replaces folder-scan detection for add/modify, making it symmetric with
git-based deletion detection. Working-tree-only edits are never clobbered.

Verification pass: folder scan ensures all mirrors byte-identical. Missing
mirrors auto-created (low risk). Content conflicts block commit with details.

Cleanup: removes empty skill dirs left by staged SKILL.md deletions.

Exit codes: 0 = all mirrors identical (safe fixes staged); 1 = out of sync
(unsafe to auto-fix; reasons logged).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure we can import the sync_skills package when loaded as a script by path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from git_helper import InvalidGitRepositoryError, get_repo  # noqa: E402

from .core import (  # noqa: E402
    _GITHUB_PATH,
    _REPO_ROOT,
    _SKILL_FILENAME,
    AGENTS,
    GIT_COMMIT_SPECIAL,
    HARDCODED_SKIPS,
    _rel,
    classify_skill_path,
    cleanup_empty_skill_dirs,
    discover_skills,
    get_skill_parents,
    is_excluded,
    mirror_slots,
    parse_staged_name_status,
)
from .sync import (  # noqa: E402
    apply_modification,
    compute_intent,
    get_staged_skill_changes,
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
    "_rel",
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
    "remove_skill_from_all_agents",
    "verify_sync",
]


def _conflict_reason(
    skill: str,
    changes: dict[str, list[tuple[str, str, bytes | None]]],
) -> str:
    blobs = {blob for _, _, blob in changes.get(skill, []) if blob is not None}
    if len(blobs) > 1:
        return (
            f"conflicting staged versions for '{skill}' across {len(blobs)} mirrors; "
            "pick one canonical version, make the others match, stage, and re-run."
        )
    if any(status == "delete" for _, status, _ in changes.get(skill, [])):
        return (
            f"'{skill}' is both staged-modified and staged-deleted; choose add or delete, "
            "stage that single intent, and re-run."
        )
    return f"unresolved staged state for '{skill}'; reconcile and re-run."


def _report_conflicts(
    conflicts: set[str],
    changes: dict[str, list[tuple[str, str, bytes | None]]],
    problems: list[str],
) -> None:
    for skill in sorted(conflicts):
        if is_excluded(skill):
            continue
        problems.append(_conflict_reason(skill, changes))


def _apply_safe_changes(
    repo_root: Path,
    skill_parents: dict[str, Path],
    changes: dict[str, list[tuple[str, str, bytes | None]]],
    problems: list[str],
) -> None:
    modifications, deletions, conflicts = compute_intent(changes)
    _report_conflicts(conflicts, changes, problems)
    for skill in deletions:
        if skill in conflicts or is_excluded(skill):
            continue
        remove_skill_from_all_agents(repo_root, skill, skill_parents, repo_root, problems)
    for skill, canonical in modifications.items():
        if skill in conflicts or is_excluded(skill):
            continue
        apply_modification(repo_root, skill, canonical, skill_parents, repo_root, problems)


def _sync_result(problems: list[str]) -> int:
    if problems:
        print("sync-skill-files: sync incomplete — the following require manual fixes:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "Safe mirror creations/propagations/deletions were applied and staged where possible. "
            "Resolve the items above, re-stage, and re-run.",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    try:
        repo_root = get_repo(_REPO_ROOT)
    except InvalidGitRepositoryError:
        print("sync-skill-files: not a git repository", file=sys.stderr)
        return 0

    skill_parents = get_skill_parents(repo_root)
    problems: list[str] = []
    changes = get_staged_skill_changes(repo_root)
    _apply_safe_changes(repo_root, skill_parents, changes, problems)
    verify_sync(repo_root, skill_parents, problems, skip=set(changes))
    cleanup_empty_skill_dirs(skill_parents, repo_root)
    return _sync_result(problems)


if __name__ == "__main__":
    sys.exit(main())

