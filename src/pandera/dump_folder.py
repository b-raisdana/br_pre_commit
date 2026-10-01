"""Process-wide configuration of the folder receiving pandera output dumps.

See README.md § "Dump folder" for usage, resolution rules, and the unresolved
``helper.repo_root`` import.
"""

from __future__ import annotations

from pathlib import Path

from br_py_log_n_profile import log_d

from ..helper.repo_root import find_repo_root

DEFAULT_DUMP_SUBPATH = Path("logs") / "output_dump"

_CUSTOM_DUMP_FOLDER: Path | None = None


def configure_pandera_dump_folder(folder: str | Path | None) -> Path | None:
    """Override the global dump folder; ``None`` restores the default.

    Applies to every subsequent dump, so it must be called before the decorated
    functions run (typically at project start-up). Returns the stored value.
    """
    global _CUSTOM_DUMP_FOLDER
    _CUSTOM_DUMP_FOLDER = None if folder is None else Path(folder)
    return _CUSTOM_DUMP_FOLDER


def configured_dump_folder() -> Path | None:
    """The configured override, or ``None`` while the default is in effect."""
    return _CUSTOM_DUMP_FOLDER


def resolve_dump_folder(source_file: Path) -> Path:
    """Absolute dump folder for a function defined in ``source_file`` (not created)."""
    folder = _CUSTOM_DUMP_FOLDER if _CUSTOM_DUMP_FOLDER is not None else DEFAULT_DUMP_SUBPATH
    if folder.is_absolute():
        return folder
    return (find_repo_root(source_file) or source_file.resolve().parent) / folder


def get_dump_folder(source_file: Path) -> Path:
    """Dump folder for ``source_file``, created on first use."""
    folder = resolve_dump_folder(source_file)
    if not folder.is_dir():
        folder.mkdir(parents=True, exist_ok=True)
        log_d(f"pandera output dump folder: {folder}")
    return folder
