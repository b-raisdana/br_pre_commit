from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Manifest:
    branch: str
    commit_hash: str
    timestamp: str
    snapshot_dir: str
    staged: list[dict[str, str]]
    unstaged: list[dict[str, str]]
    untracked: list[dict[str, str]]
