#!/usr/bin/env python3
"""Core utilities for sync-skill-files.

Constants, path/git helpers, skill classification, mirror locations,
git status parsing, skill discovery, and cleanup.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

from git import Repo
from git.exc import GitCommandError

AGENTS = [
    "claude",
    "codex",
    "devin",
    "qoder",
    "copilot",
    "kiro",
    "kilo",
]

HARDCODED_SKIPS = {"use-aget-skills", "kilo-only-todo-discipline"}

GIT_COMMIT_SPECIAL = "git-commit"
_GITHUB_PATH = ".github/git-commit"

_REPO_ROOT = Path(os.environ.get("BR_PRE_COMMIT_REPO_ROOT", Path.cwd())).resolve()
_SKILL_FILENAME = "SKILL.md"


def is_excluded(skill_dir: str) -> bool:
    return skill_dir in HARDCODED_SKIPS or any(skill_dir.startswith(f"{a}-only-") for a in AGENTS)


def get_skill_parents(repo_root: Path) -> dict[str, Path]:
    return {a: repo_root / f".{a}" / "skills" for a in AGENTS if (repo_root / f".{a}" / "skills").is_dir()}


def _rel(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _index_bytes(repo: Repo, rel: str) -> bytes | None:
    buf = io.BytesIO()
    try:
        repo.git.show(f":{rel}", output_stream=buf)
    except GitCommandError:
        return None
    return buf.getvalue()


def _stage(repo: Repo, rel: str) -> None:
    repo.git.add(rel)


def classify_skill_path(path_str: str) -> tuple[str, str] | None:
    """Map a SKILL.md path to ``(skill_name, slot_key)`` (``slot_key`` is an agent slug or ``.github``)."""
    parts = Path(path_str).parts
    if len(parts) == 4 and parts[0].startswith(".") and parts[1] == "skills" and parts[3] == _SKILL_FILENAME:
        agent = parts[0].lstrip(".")
        if agent in AGENTS:
            return parts[2], agent
    if len(parts) == 3 and parts == (".github", GIT_COMMIT_SPECIAL, _SKILL_FILENAME):
        return GIT_COMMIT_SPECIAL, _GITHUB_PATH
    return None


def mirror_slots(repo_root: Path, skill_parents: dict[str, Path], skill_name: str) -> list[tuple[str, Path]]:
    """All mirror locations for a skill (the ``.github`` slot only for git-commit)."""
    slots: list[tuple[str, Path]] = []
    for agent, parent in skill_parents.items():
        slots.append((agent, parent / skill_name / _SKILL_FILENAME))
    if skill_name == GIT_COMMIT_SPECIAL:
        slots.append((_GITHUB_PATH, repo_root / _GITHUB_PATH / _SKILL_FILENAME))
    return slots


def parse_staged_name_status(raw: str) -> list[tuple[str, str]]:
    """Parse ``git diff --cached --name-status`` into ``[(path, status_letter)]``.

    For renames/copies the *new* path is returned (the skill's canonical
    location) with letter ``R`` -- ``--name-status`` emits ``R<N>\told\tnew``.
    Non-staged rows (e.g. ``??`` untracked) never appear in ``--cached``; any
    unknown leading letter is ignored so new git status codes can't break it.
    """
    entries: list[tuple[str, str]] = []
    for line in raw.splitlines():
        fields = line.split("\t")
        if not fields:
            continue
        code = fields[0][0]
        if code in ("R", "C") and len(fields) >= 3:
            entries.append((fields[2], code))
        elif code in ("A", "M", "D"):
            entries.append((fields[1], code))
    return entries


def cleanup_empty_skill_dirs(skill_parents: dict[str, Path], repo_root: Path) -> list[str]:
    """Remove empty skill directories left behind after SKILL.md deletions.

    Git does not track empty directories, so a staged deletion of a skill's
    ``SKILL.md`` leaves an empty ``<parent>/<skill-name>`` folder on disk. This
    sweeps every agent skill parent (and the ``.github/git-commit`` slot) and
    removes any skill directory that is completely empty, keeping the working
    tree tidy. Only directories with no entries are touched -- anything that still
    contains files (e.g. workflow files alongside the ``.github/git-commit``
    skill) is left untouched. Safe to run unconditionally; best-effort.
    """
    removed: list[str] = []
    for parent in skill_parents.values():
        if not parent.is_dir():
            continue
        for skill_dir in parent.iterdir():
            if skill_dir.is_dir() and not any(skill_dir.iterdir()):
                skill_dir.rmdir()
                removed.append(_rel(skill_dir, repo_root))
    gh_skill_dir = repo_root / _GITHUB_PATH
    if gh_skill_dir.is_dir() and not any(gh_skill_dir.iterdir()):
        gh_skill_dir.rmdir()
        removed.append(_rel(gh_skill_dir, repo_root))
    return removed


def discover_skills(skill_parents: dict[str, Path], repo_root: Path) -> set[str]:
    seen = set()
    for parent in skill_parents.values():
        for skill_dir in parent.iterdir():
            if skill_dir.is_dir() and (skill_dir / _SKILL_FILENAME).is_file():
                seen.add(skill_dir.name)
    if (repo_root / _GITHUB_PATH / _SKILL_FILENAME).is_file():
        seen.add(GIT_COMMIT_SPECIAL)
    return seen
