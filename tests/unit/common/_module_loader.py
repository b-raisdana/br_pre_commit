"""Load script-like modules used by tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_script(path: Path, name: str | None = None, *, add_parent_to_path: bool = False) -> ModuleType:
    path = path.resolve()
    if add_parent_to_path:
        sys.path.insert(0, str(path.parent))

    spec = importlib.util.spec_from_file_location(name or path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module from {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
