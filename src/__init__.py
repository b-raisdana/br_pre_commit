"""Implementation package for br_pre_commit.

Entry points live in sibling modules (``src.ratchet``, ``src.sync_skills``,
``src.install``, ...), so importing this package must stay cheap: it only exposes
``pandera_validate`` and does so lazily (PEP 562). Importing it eagerly would pull
pandas/pandera into every hook process and would make ``src.install`` require the
``BR_PRE_COMMIT_REPO_ROOT`` / ``USER_REPO_ROOT`` settings that it is the one
responsible for discovering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .br_pandera.__main__ import pandera_validate

__all__ = ["pandera_validate"]


def __getattr__(name: str) -> Any:
    if name == "pandera_validate":
        from .br_pandera.__main__ import pandera_validate

        return pandera_validate
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
