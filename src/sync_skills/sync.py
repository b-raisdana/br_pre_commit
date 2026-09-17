#!/usr/bin/env python3
"""Sync operations for sync-skill-files.

Staged changes detection, intent computation, mirror removal,
modification application, and verification.
"""

from __future__ import annotations

from pathlib import Path

from git import Repo

from sync_skills.core import (
    _index_bytes,
    _rel,
    _stage,
    classify_skill_path,
    discover_skills,
    is_excluded,
    mirror_slots,
    parse_staged_name_status,
)


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


def _skill_intent(
    entries: list[tuple[str, str, bytes | None]],
) -> tuple[bytes | None, bool, bool]:
    blobs = {blob for _, status, blob in entries if status != "delete" and blob is not None}
    deleted = any(status == "delete" for _, status, _ in entries)
    if deleted:
        return None, True, bool(blobs)
    if len(blobs) > 1:
        return None, False, True
    if blobs:
        return next(iter(blobs)), False, False
    return None, False, False


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
        canonical, deleted, conflicted = _skill_intent(entries)
        if deleted:
            deletions.add(skill)
        if conflicted:
            conflicts.add(skill)
        if canonical is not None:
            modifications[skill] = canonical
    return modifications, deletions, conflicts


def remove_mirror(
    repo: Repo,
    skill_name: str,
    slot: str,
    path: Path,
    repo_root: Path,
    problems: list[str],
) -> bool:
    """Stage the deletion of one mirror if it is safe to do so.

    Returns ``True`` when the mirror was actually removed (and staged), ``False``
    when it was already gone or could not be safely removed.
    """
    rel = _rel(path, repo_root)
    idx = _index_bytes(repo, rel)
    work = path.read_bytes() if path.exists() else None
    if work is None and idx is None:
        return False  # already gone
    if idx is not None and (work is None or work == idx):
        # Clean tracked mirror (or staged-deleted already reflected in worktree) -> stage deletion.
        path.unlink(missing_ok=True)
        _stage(repo, rel)
        return True
    problems.append(
        f"mirror '{skill_name}' in {slot} ({rel}) has uncommitted/untracked content that a staged "
        f"deletion would discard; stage the deletion intentionally (git rm) or reconcile, then re-run."
    )
    return False


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


def _create_missing_mirrors(
    repo: Repo,
    repo_root: Path,
    skill_name: str,
    canonical: bytes,
    skill_parents: dict[str, Path],
) -> None:
    for _, path in mirror_slots(repo_root, skill_parents, skill_name):
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(canonical)
            _stage(repo, _rel(path, repo_root))


def _report_divergence(skill_name: str, present: list[tuple[str, Path]], repo_root: Path, problems: list[str]) -> None:
    detail = ", ".join(f"{slot}: {_rel(p, repo_root)}" for slot, p in present)
    problems.append(
        f"out-of-sync mirrors for '{skill_name}': {detail}. Edit one mirror to the desired "
        f"content, copy it to the others (e.g. cp <chosen>/SKILL.md <other>/SKILL.md), stage, "
        f"and re-run."
    )


def _check_skill_sync(
    repo: Repo,
    repo_root: Path,
    skill_name: str,
    skill_parents: dict[str, Path],
    problems: list[str],
) -> None:
    slots = mirror_slots(repo_root, skill_parents, skill_name)
    present = [(slot, p) for slot, p in slots if p.exists()]
    if not present:
        return
    contents = {p.read_bytes() for _, p in present}
    if len(contents) == 1:
        _create_missing_mirrors(repo, repo_root, skill_name, contents.pop(), skill_parents)
        return
    _report_divergence(skill_name, present, repo_root, problems)


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
        _check_skill_sync(repo, repo_root, skill_name, skill_parents, problems)
