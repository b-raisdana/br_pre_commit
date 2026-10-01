"""Check that br_pre_commit's own requirements are installed.

``requirements.txt`` is the single source of truth: it is parsed and every
requirement is resolved against the active environment through
``importlib.metadata``, so the check covers both presence and version bounds.
A hand-maintained list of import names drifts out of sync with
``requirements.txt`` and lets an uninstalled dependency reach the hooks.
"""

from __future__ import annotations

import os
import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

# br_pre_commit/src/helper/requirements.py -> br_pre_commit/
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]

_INCLUDE_LINE = re.compile(r"^\s*(-|\s*--)")
_COMMENT_LINE = re.compile(r"^\s*(#|$)")
# A trailing comment is whitespace followed by '#'; a '#' glued to a token (e.g. a URL
# fragment) is part of the requirement and must survive.
_TRAILING_COMMENT = re.compile(r"\s+#.*$")


def get_br_pre_commit_repo_root() -> Path:
    """Locate the br_pre_commit checkout: ``BR_PRE_COMMIT_REPO_ROOT`` if set, else this package."""
    from_env = os.environ.get("BR_PRE_COMMIT_REPO_ROOT")
    return Path(from_env).resolve() if from_env else DEFAULT_REPO_ROOT


def get_requirements_txt_path(repo_root: Path | None = None) -> Path:
    return (repo_root or get_br_pre_commit_repo_root()) / "requirements.txt"


def parse_requirements_txt(requirements_txt_path: Path) -> list[Requirement]:
    """Read requirements.txt into Requirement objects, ignoring comments, options and includes."""
    requirements: list[Requirement] = []
    lines = _join_continuations(requirements_txt_path.read_text(encoding="utf-8").splitlines())
    for line in lines:
        line = _TRAILING_COMMENT.sub("", line)
        if _COMMENT_LINE.match(line) or _INCLUDE_LINE.match(line):
            continue
        try:
            requirements.append(Requirement(line))
        except InvalidRequirement:
            continue
    return requirements


def _join_continuations(lines: list[str]) -> list[str]:
    joined: list[str] = []
    buffer = ""
    for raw_line in lines:
        line = raw_line.rstrip()
        if line.endswith("\\"):
            buffer += line[:-1] + " "
            continue
        joined.append(buffer + line)
        buffer = ""
    if buffer:
        joined.append(buffer)
    return joined


def unsatisfied_requirements(repo_root: Path | None = None) -> list[str]:
    """Return one message per requirement that is not satisfied by the active environment.

    The message names the requirement, the bound it declares and the version found
    (or "not installed"), so the caller can print it verbatim.
    """
    requirements_txt_path = get_requirements_txt_path(repo_root)
    if not requirements_txt_path.exists():
        return [f"requirements file not found: {requirements_txt_path}"]

    unsatisfied: list[str] = []
    for requirement in parse_requirements_txt(requirements_txt_path):
        bound = str(requirement.specifier) or "any version"
        try:
            found = installed_version(requirement.name)
        except PackageNotFoundError:
            unsatisfied.append(f"{requirement.name} (required {bound}) - not installed")
            continue
        if requirement.specifier and not requirement.specifier.contains(found, prereleases=True):
            unsatisfied.append(f"{requirement.name} (required {bound}) - installed {found}")
    return unsatisfied
