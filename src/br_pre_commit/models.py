from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Manifest:
    branch: str
    commit_hash: str
    timestamp: str
    snapshot_dir: str
    staged: list[dict[str, str]]
    unstaged: list[dict[str, str]]
    untracked: list[dict[str, str]]
    full_backups: list[dict[str, str]] = field(default_factory=list)
