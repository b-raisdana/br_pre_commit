#!/usr/bin/env python3
"""Interactive conflict resolution for sync-skill-files.

Resolves, together with the user, the conflicts the sync hook blocks on:
conflicting staged versions of one skill, a skill that is both
staged-modified and staged-deleted, and mirrors that diverge with no
single canonical staged version.

Run from the repository root:

    python -m src.sync_skills.resolve

For every diverging skill it lists each mirror's version with a short
preview, asks which one is canonical (or whether to delete the skill),
then applies the choice to every mirror through the same safe write path
the hook uses (missing mirrors created, clean mirrors updated and staged,
mirrors with uncommitted/untracked edits never clobbered).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from ..helper.paths import get_user_repo_root_from_git, git_subprocess_env


def _discover_br_pre_commit_repo_root() -> Path:
    """Toplevel of the git repository this module's checkout lives in."""
    return Path(
        subprocess.check_output(
            ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--show-toplevel"],
            text=True,
            env=git_subprocess_env(),
        ).strip()
    )


def _ensure_repo_root_env_vars() -> None:
    """Set USER_REPO_ROOT / BR_PRE_COMMIT_REPO_ROOT when this shell lacks them.

    The pre-commit hook that src/install.py generates exports both
    variables (see install.py's generate_posix_hook /
    generate_powershell_hook); a direct
    ``python -m src.sync_skills.resolve`` run may not have them, and
    ``sync_skills.config`` reads USER_REPO_ROOT at import time (when
    ``.core`` is imported below). Like install.py, discover the
    missing roots from git, print them, and ask for confirmation.
    Must run before importing ``.core``.
    """
    missing: list[tuple[str, Path]] = []
    if not os.environ.get("USER_REPO_ROOT"):
        try:
            missing.append(("USER_REPO_ROOT", get_user_repo_root_from_git()))
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            print(
                f"sync-skill-files resolve: cannot detect the user repository root: {exc}\n"
                "Run install.sh / install.ps1 to generate the hook that exports "
                "USER_REPO_ROOT, or export it manually, and re-run.",
                file=sys.stderr,
            )
            sys.exit(1)
    if not os.environ.get("BR_PRE_COMMIT_REPO_ROOT"):
        try:
            missing.append(("BR_PRE_COMMIT_REPO_ROOT", _discover_br_pre_commit_repo_root()))
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            print(
                f"sync-skill-files resolve: cannot detect the br_pre_commit repository root: {exc}\n"
                "Run install.sh / install.ps1 to generate the hook that exports "
                "BR_PRE_COMMIT_REPO_ROOT, or export it manually, and re-run.",
                file=sys.stderr,
            )
            sys.exit(1)
    if not missing:
        return
    print("sync-skill-files resolve: repo roots not set in this shell:")
    for name, path in missing:
        print(f"  {name} = {path}")
    try:
        answer = input("Do you confirm? [y/N]: ").strip().lower()
    except EOFError:
        answer = ""
    if answer not in ("y", "yes"):
        print(
            "Aborted; run install.sh / install.ps1 to generate the hook that "
            "exports the variables, or export them manually, and re-run.",
        )
        sys.exit(1)
    for name, path in missing:
        os.environ[name] = str(path)


_ensure_repo_root_env_vars()

from ..helper.git import InvalidGitRepositoryError, get_repo  # noqa: E402
from .core import (  # noqa: E402
    _BR_PRE_COMMIT_REPO_ROOT,
    _GITHUB_PATH,
    _SKILL_FILENAME,
    _rel,
    discover_skills,
    get_skill_parents,
    is_excluded,
    mirror_slots,
)
from .sync import (  # noqa: E402
    apply_modification,
    compute_intent,
    get_staged_skill_changes,
    remove_skill_from_all_agents,
    verify_sync,
)

_Ask = Callable[[str], str]


def _preview(blob: bytes) -> str:
    text = blob.decode(errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:79]
    return "<empty file>"


def _ask_choice(ask: _Ask, skill: str, candidates: dict[bytes, list[str]]) -> bytes | None:
    blobs = list(candidates)
    print(f"'{skill}' has {len(blobs)} diverging versions:")
    for number, blob in enumerate(blobs, start=1):
        mirrors = ", ".join(candidates[blob])
        print(f"  {number}) [{mirrors}] {_preview(blob)}")
    prompt = f"Choose the canonical version for '{skill}' (1-{len(blobs)}), or Enter to skip: "
    while True:
        try:
            answer = ask(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not answer:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(blobs):
            return blobs[int(answer) - 1]
        print(f"Enter a number between 1 and {len(blobs)}, or Enter to skip.")


def _ask_keep_or_delete(ask: _Ask, skill: str) -> str | None:
    prompt = (
        f"'{skill}' is both staged-modified and staged-deleted. "
        "Keep the staged version or delete it everywhere? [keep/delete] "
    )
    while True:
        try:
            answer = ask(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if answer in ("keep", "k"):
            return "keep"
        if answer in ("delete", "d"):
            return "delete"
        print("Answer 'keep'/'k' or 'delete'/'d'.")


def _slot_label(slot: str, skill: str) -> str:
    if slot == _GITHUB_PATH:
        return f"{slot} ({_GITHUB_PATH}/{_SKILL_FILENAME})"
    return f"{slot} (.{slot}/skills/{skill}/{_SKILL_FILENAME})"


def _staged_candidates(
    skill: str,
    entries: list[tuple[str, str, bytes | None]],
) -> dict[bytes, list[str]]:
    candidates: dict[bytes, list[str]] = {}
    for slot, _, blob in entries:
        if blob is not None:
            candidates.setdefault(blob, []).append(_slot_label(slot, skill))
    return candidates


def _worktree_candidates(
    br_pre_commit_repo_root: Path,
    skill_parents: dict[str, Path],
    skill_name: str,
) -> dict[bytes, list[str]]:
    candidates: dict[bytes, list[str]] = {}
    for slot, path in mirror_slots(br_pre_commit_repo_root, skill_parents, skill_name):
        if path.exists():
            label = f"{slot} ({_rel(path, br_pre_commit_repo_root)})"
            candidates.setdefault(path.read_bytes(), []).append(label)
    return candidates


def _resolve_staged_conflict(
    skill: str,
    entries: list[tuple[str, str, bytes | None]],
    br_pre_commit_repo_root: Path,
    skill_parents: dict[str, Path],
    ask: _Ask,
    problems: list[str],
) -> None:
    candidates = _staged_candidates(skill, entries)
    deleted = any(status == "delete" for _, status, _ in entries)
    if deleted:
        choice = _ask_keep_or_delete(ask, skill)
        if choice == "delete":
            remove_skill_from_all_agents(br_pre_commit_repo_root, skill, skill_parents, problems)
            return
        if choice is None:
            problems.append(f"'{skill}' left unresolved; reconcile by hand and re-run sync-skill-files.")
            return
    if not candidates:
        return
    canonical: bytes | None
    if len(candidates) == 1:
        canonical = next(iter(candidates))
    else:
        canonical = _ask_choice(ask, skill, candidates)
        if canonical is None:
            problems.append(f"'{skill}' left unresolved; pick one version, make the others match, stage, and re-run.")
            return
    apply_modification(br_pre_commit_repo_root, skill, canonical, skill_parents, problems)


def _resolve_divergence(
    br_pre_commit_repo_root: Path,
    skill_parents: dict[str, Path],
    ask: _Ask,
    problems: list[str],
    skip: set[str] | None = None,
) -> set[str]:
    unresolved: set[str] = set()
    handled = skip or set()
    for skill in sorted(discover_skills(skill_parents, br_pre_commit_repo_root)):
        if is_excluded(skill) or skill in handled:
            continue
        candidates = _worktree_candidates(br_pre_commit_repo_root, skill_parents, skill)
        if len(candidates) < 2:
            continue
        canonical = _ask_choice(ask, skill, candidates)
        if canonical is None:
            problems.append(f"'{skill}' left unresolved; pick one version, make the others match, stage, and re-run.")
            unresolved.add(skill)
            continue
        apply_modification(br_pre_commit_repo_root, skill, canonical, skill_parents, problems)
    return unresolved


def interactive_resolve(
    br_pre_commit_repo_root: Path,
    ask: _Ask = input,
) -> int:
    skill_parents = get_skill_parents(br_pre_commit_repo_root)
    problems: list[str] = []
    changes = get_staged_skill_changes(br_pre_commit_repo_root)
    _, _, conflicts = compute_intent(changes)
    handled: set[str] = set()
    for skill in sorted(conflicts):
        if is_excluded(skill):
            continue
        _resolve_staged_conflict(skill, changes.get(skill, []), br_pre_commit_repo_root, skill_parents, ask, problems)
        handled.add(skill)
    unresolved = _resolve_divergence(br_pre_commit_repo_root, skill_parents, ask, problems, skip=handled)
    verify_sync(br_pre_commit_repo_root, skill_parents, problems, skip=set(changes) | unresolved)
    if problems:
        print("sync-skill-files resolve: the following still need manual fixes:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("Resolve the items above, re-stage, and re-run.", file=sys.stderr)
        return 1
    print("sync-skill-files resolve: all mirrors are now identical.")
    return 0


def main() -> int:
    try:
        br_pre_commit_repo_root = asyncio.run(get_repo(_BR_PRE_COMMIT_REPO_ROOT))
    except InvalidGitRepositoryError:
        print("sync-skill-files resolve: not a git repository", file=sys.stderr)
        return 0
    if not sys.stdin.isatty():
        print(
            "sync-skill-files resolve: needs an interactive terminal. "
            "Manual alternative: copy the chosen SKILL.md over the other mirrors, "
            "stage, and re-run sync-skill-files.",
            file=sys.stderr,
        )
        return 1
    return interactive_resolve(br_pre_commit_repo_root)


if __name__ == "__main__":
    sys.exit(main())
