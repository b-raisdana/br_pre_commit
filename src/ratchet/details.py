"""Detail printers for the incremental pre-commit ratchet.

Holds the per-tool detail printers (ruff, mypy, xenon, loc) and the
``DETAIL_PRINTERS`` registry so that ``__main__.py`` stays under the LOC cap.

Functions look up helper symbols through the ``baseline`` module at call time so
that tests can monkeypatch ``baseline_module.run_output`` / ``run`` /
``_line_count`` and have the detail printers honour those patches.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from helper.paths import get_user_repo_path_from_env

from . import baseline as _baseline
from . import tools as _tools
from .config import ratchet_config


def print_ruff_details(paths: list[Path]) -> None:
    if not paths:
        print("    no files to inspect")
        return
    output = _baseline.run_output("ruff", "check", *(path.as_posix() for path in paths))
    print(output.rstrip() or "    ruff reported no errors on these files")


def print_mypy_details(paths: list[Path]) -> None:
    app_paths = [path.relative_to(ratchet_config.target_dir_rel_path).as_posix() for path in paths]
    if not app_paths:
        print("    no files to inspect")
        return
    config_path = str(get_user_repo_path_from_env() / "pyproject.toml")
    cwd = get_user_repo_path_from_env() / ratchet_config.target_dir_rel_path
    output = _baseline.run_output("mypy", "--config-file", config_path, *app_paths, cwd=cwd)
    print(output.rstrip() or "    mypy reported no errors on these files")


def print_xenon_details(paths: list[Path], max_absolute: str = "B") -> None:
    paths = _tools._exclude_tests(paths)
    if not paths:
        print("    no files to inspect")
        return
    exclude_dirs = ",".join(ratchet_config.exclude_dirs)
    stdout = _baseline.run(
        "radon",
        "cc",
        str(ratchet_config.target_dir_rel_path),
        "-j",
        "-i",
        f"tests,{exclude_dirs}",
        "--show-closures",
        cwd=get_user_repo_path_from_env(),
    )
    data = _tools._parse_xenon_json(stdout)
    threshold = ratchet_config.xenon_complexity_ranks.index(ratchet_config.xenon_max_absolute)
    printed = False
    for file_path, blocks in sorted(data.items()):
        for block in blocks:
            rank = block.get("rank", "A")
            if ratchet_config.xenon_complexity_ranks.index(rank) <= threshold:
                continue
            print(f"    {file_path}:{block.get('lineno')} {block.get('type')} {block.get('name')} rank {rank}")
            printed = True
    if not printed:
        print(f"    xenon/radon reported no rank > {ratchet_config.xenon_max_absolute} blocks on these files")


def print_loc_details(paths: list[Path], max_lines: int = 300) -> None:
    for path in paths:
        print(
            f"    {path.as_posix()}: {_baseline._line_count(get_user_repo_path_from_env() / path)} lines "
            f"(cap {max_lines}, slack {ratchet_config.loc_line_growth_slack})"
        )


DETAIL_PRINTERS: dict[str, Callable[[list[Path]], None]] = {
    "ruff": print_ruff_details,
    "mypy": print_mypy_details,
    "xenon": print_xenon_details,
    "loc": print_loc_details,
}
