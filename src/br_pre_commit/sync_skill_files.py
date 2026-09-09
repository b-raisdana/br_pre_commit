#!/usr/bin/env python3
"""Sync mirrored skill files across agent directories.

Bidirectional mirror of ``SKILL.md`` across ``.claude/skills``, ``.codex/skills``,
``.devin/skills``, ``.qoder/skills``, ``.copilot/skills``, ``.kiro/skills``,
``.kilo/skills`` (and, for the ``git-commit`` skill only, ``.github/git-commit``).

Detection strategy
------------------
The set of skills that need attention comes **only** from the git staged state
(``git diff --cached --name-status``): additions, modifications, renames and
staged deletions. That is the source of truth for *what is being committed*; it
replaces the old folder-scan-detection for add/modify (which was asymmetric with
the git-based deletion detector).

Working-tree-only edits that are not (yet) staged are never silently clobbered:
a mirror whose worktree differs from its staged (index) version is treated as
uncommitted work in progress and left for the user.

After the git-driven sync, the hook does a full folder scan purely as a
**verification** pass: every shared skill's mirrors must end up byte-identical.
A mirror that is simply *missing* (a skill added to one agent but not yet to the
others) is created automatically — low-risk, since there is nothing to clobber.
A genuine *content conflict* — two mirrors whose bytes already diverge and
neither is the single canonical staged version — is not auto-fixed: the hook
prints exactly which agents diverge and the manual steps to resolve them, then
exits non-zero to block the commit.

Exit codes
----------
* ``0`` — every shared skill's mirrors are byte-identical across all agents
  (safe auto-fixes were applied and staged; the developer is not bothered).
* ``1`` — one or more skills are out of sync and the divergence is unsafe to
  auto-fix. Reasons and manual steps are logged to stderr.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError

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
    if skill_dir in HARDCODED_SKIPS:
        return True
    return any(skill_dir.startswith(f"{agent}-only-") for agent in AGENTS)


def get_skill_parents(repo_root: Path) -> dict[str, Path]:
    parents = {}
    for agent in AGENTS:
        parent = repo_root / f".{agent}" / "skills"
        if parent.is_dir():
            parents[agent] = parent
    return parents


def _rel(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _index_bytes(repo: Repo, rel: str) -> bytes | None:
    """Bytes of a path in the git index (``git show :path``), or None if untracked/unknown."""
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


def get_staged_skill_changes(repo: Repo) -> dict[str, list[tuple[str, str, bytes | None]]]:
    """Detect staged skill changes from git (the source of truth for add/modify/delete).

    Returns ``skill_name -> [(slot_key, status, staged_blob)]`` where ``status`` is
    ``"add"``, ``"modify"``, ``"rename"`` or ``"delete"`` and ``staged_blob`` is the
    index content for add/modify/rename (``None`` for delete).
    """
    status_map = {"A": "add", "M": "modify", "R": "rename", "C": "rename"}
    by_skill: dict[str, list[tuple[str, str, bytes | None]]] = {}
    for path, code in parse_staged_name_status(repo.git.diff("--cached", "--name-status")):
        classified = classify_skill_path(path)
        if classified is None:
            continue
        skill_name, slot_key = classified
        if code == "D":
            status, blob = "delete", None
        else:
            status, blob = status_map.get(code, "modify"), _index_bytes(repo, path)
        by_skill.setdefault(skill_name, []).append((slot_key, status, blob))
    return by_skill


def compute_intent(
    changes: dict[str, list[tuple[str, str, bytes | None]]],
) -> tuple[dict[str, bytes], set[str], set[str]]:
    """Derive a safe sync plan from staged changes.

    Returns:
    - ``modifications``: skill -> single canonical staged blob (only when exactly
      one distinct staged version exists and the skill is not also staged-deleted).
    - ``deletions``: skills staged for deletion.
    - ``conflicts``: skills that are unsafe to auto-fix (multiple staged versions
      and/or both modified and deleted).
    """
    modifications: dict[str, bytes] = {}
    deletions: set[str] = set()
    conflicts: set[str] = set()
    for skill, entries in changes.items():
        is_deleted = any(status == "delete" for _, status, _ in entries)
        mod_blobs = {b for _, status, b in entries if status != "delete" and b is not None}
        if is_deleted:
            deletions.add(skill)
            if mod_blobs:
                conflicts.add(skill)
        if len(mod_blobs) > 1:
            conflicts.add(skill)
        elif len(mod_blobs) == 1 and not is_deleted:
            modifications[skill] = next(iter(mod_blobs))
    return modifications, deletions, conflicts


def apply_modification(
    repo: Repo,
    skill_name: str,
    canonical: bytes,
    skill_parents: dict[str, Path],
    repo_root: Path,
    problems: list[str],
) -> None:
    """Propagate ``canonical`` to every mirror of ``skill_name``, staging safe writes.

    Mirrors with uncommitted work that would be clobbered are recorded in
    ``problems`` instead of touched.
    """
    for slot, path in mirror_slots(repo_root, skill_parents, skill_name):
        if is_excluded(skill_name):
            continue
        rel = _rel(path, repo_root)
        idx = _index_bytes(repo, rel)
        work = path.read_bytes() if path.exists() else None
        if work is None:
            # Missing mirror -> safe to create (nothing to clobber).
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(canonical)
            _stage(repo, rel)
        elif work == canonical:
            # Worktree already canonical; just make sure the index agrees (idempotent).
            if idx != canonical:
                _stage(repo, rel)
        elif idx is None:
            # Untracked file carrying different content -> clobbering would lose work.
            problems.append(
                f"untracked mirror for '{skill_name}' in {slot} ({rel}) diverges from the canonical "
                f"staged version; reconcile by hand, then re-run."
            )
        elif idx == work:
            # Clean (staged-or-HEAD) mirror that lags the canonical version -> safe to update.
            path.write_bytes(canonical)
            _stage(repo, rel)
        else:
            # index != worktree -> uncommitted edits at risk of being overwritten.
            problems.append(
                f"mirror '{skill_name}' in {slot} ({rel}) has uncommitted edits that a staged sync "
                f"would overwrite; finish or stash them, then re-run."
            )


def remove_mirror(
    repo: Repo,
    skill_name: str,
    slot: str,
    path: Path,
    repo_root: Path,
    problems: list[str],
) -> None:
    """Stage the deletion of one mirror if it is safe to do so."""
    rel = _rel(path, repo_root)
    idx = _index_bytes(repo, rel)
    work = path.read_bytes() if path.exists() else None
    if work is None and idx is None:
        return  # already gone
    if idx is not None and (work is None or work == idx):
        # Clean tracked mirror (or staged-deleted already reflected in worktree) -> stage deletion.
        path.unlink(missing_ok=True)
        _stage(repo, rel)
        return
    problems.append(
        f"mirror '{skill_name}' in {slot} ({rel}) has uncommitted/untracked content that a staged "
        f"deletion would discard; stage the deletion intentionally (git rm) or reconcile, then re-run."
    )


def remove_skill_from_all_agents(
    repo: Repo,
    skill_name: str,
    skill_parents: dict[str, Path],
    repo_root: Path,
    problems: list[str],
) -> bool:
    changed = False
    for slot, path in mirror_slots(repo_root, skill_parents, skill_name):
        if is_excluded(skill_name):
            continue
        if remove_mirror(repo, skill_name, slot, path, repo_root, problems):
            changed = True
    return changed


def discover_skills(skill_parents: dict[str, Path], repo_root: Path) -> set[str]:
    seen = set()
    for parent in skill_parents.values():
        for skill_dir in parent.iterdir():
            if skill_dir.is_dir() and (skill_dir / _SKILL_FILENAME).is_file():
                seen.add(skill_dir.name)
    if (repo_root / _GITHUB_PATH / _SKILL_FILENAME).is_file():
        seen.add(GIT_COMMIT_SPECIAL)
    return seen


def verify_sync(
    repo: Repo,
    repo_root: Path,
    skill_parents: dict[str, Path],
    problems: list[str],
    skip: set[str] | None = None,
) -> None:
    """Folder-scan verification: every shared skill's mirrors must be byte-identical.

    Missing mirrors (with identical existing copies) are created automatically —
    low risk. Genuine content divergence is reported as a blocking problem.
    Skills in ``skip`` (already reported via staged-conflict / WIP problems this
    run) are left to that earlier, more specific message to avoid double-reporting.
    """
    skip = skip or set()
    for skill_name in discover_skills(skill_parents, repo_root):
        if is_excluded(skill_name) or skill_name in skip:
            continue
        slots = mirror_slots(repo_root, skill_parents, skill_name)
        present = [(slot, p) for slot, p in slots if p.exists()]
        if not present:
            continue
        contents = {p.read_bytes() for _, p in present}
        if len(contents) == 1:
            # Identical copies: fill any missing mirrors (low risk).
            canonical = contents.pop()
            for _, p in slots:
                if not p.exists():
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(canonical)
                    _stage(repo, _rel(p, repo_root))
            continue
        detail = ", ".join(f"{slot}: {_rel(p, repo_root)}" for slot, p in present)
        problems.append(
            f"out-of-sync mirrors for '{skill_name}': {detail}. Edit one mirror to the desired "
            f"content, copy it to the others (e.g. cp <chosen>/SKILL.md <other>/SKILL.md), stage, "
            f"and re-run."
        )


def main() -> int:
    try:
        repo = Repo(_REPO_ROOT)
    except InvalidGitRepositoryError:
        print("sync-skill-files: not a git repository", file=sys.stderr)
        return 0

    repo_root = _REPO_ROOT
    skill_parents = get_skill_parents(repo_root)
    problems: list[str] = []

    # 1. Source of truth: staged changes from git.
    changes = get_staged_skill_changes(repo)
    modifications, deletions, conflicts = compute_intent(changes)

    if conflicts:
        for skill in sorted(conflicts):
            if is_excluded(skill):
                continue
            blobs = {b for _, _, b in changes.get(skill, []) if b is not None}
            if len(blobs) > 1:
                reason = (
                    f"conflicting staged versions for '{skill}' across {len(blobs)} mirrors; "
                    f"pick one canonical version, make the others match, stage, and re-run."
                )
            elif any(s == "delete" for _, s, _ in changes.get(skill, [])):
                reason = (
                    f"'{skill}' is both staged-modified and staged-deleted; choose add or delete, "
                    f"stage that single intent, and re-run."
                )
            else:
                reason = f"unresolved staged state for '{skill}'; reconcile and re-run."
            problems.append(reason)

    # 2. Safe staged deletions -> remove from all mirrors.
    for skill in deletions:
        if skill in conflicts or is_excluded(skill):
            continue
        remove_skill_from_all_agents(repo, skill, skill_parents, repo_root, problems)

    # 3. Safe staged modifications -> propagate canonical to all mirrors.
    for skill, canonical in modifications.items():
        if skill in conflicts or is_excluded(skill):
            continue
        apply_modification(repo, skill, canonical, skill_parents, repo_root, problems)

    # 4. Final verification: folder scan confirms every mirror is byte-identical.
    #    Skip skills already flagged above (their specific conflict/WIP message suffices).
    verify_sync(repo, repo_root, skill_parents, problems, skip=set(changes))

    if problems:
        print("sync-skill-files: sync incomplete — the following require manual fixes:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "Safe mirror creations/propagations/deletions were applied and staged where possible. "
            "Resolve the items above, re-stage, and re-run.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
