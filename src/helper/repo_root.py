"""Repository root finder helper for pandera validation decorator."""

from __future__ import annotations

from pathlib import Path


def find_repo_root(source_file: Path) -> Path | None:
    """Find the Git repository root containing the given source file.

    Args:
        source_file: Path to a source file in the repository

    Returns:
        Path to the repository root, or None if not found
    """
    current = source_file.resolve().parent
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None
