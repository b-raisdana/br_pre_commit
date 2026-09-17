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

from . import baseline as _baseline
from . import tools as _tools


def print_ruff_details(paths: list[Path]) -> None:
    if not paths:
        print("    no files to inspect")
        return
    output = _baseline.run_output("ruff", "check", *(path.as_posix() for path in paths))
    print(output.rstrip() or "    ruff reported no errors on these files")


def print_mypy_details(paths: list[Path]) -> None:
    app_paths = [path.relative_to(_baseline.TARGET).as_posix() for path in paths]
    if not app_paths:
        print("    no files to inspect")
        return
    config_path = str(_baseline.ROOT / "pyproject.toml")
    cwd = _baseline.ROOT / _baseline.TARGET
    output = _baseline.run_output("mypy", "--config-file", config_path, *app_paths, cwd=cwd)
    print(output.rstrip() or "    mypy reported no errors on these files")


def print_xenon_details(paths: list[Path], max_absolute: str = "B") -> None:
    paths = _tools._exclude_tests(paths)
    if not paths:
        print("    no files to inspect")
        return
    stdout = _baseline.run(
        "radon",
        "cc",
        _baseline.TARGET,
        "-j",
        "-i",
        f"tests,{_baseline.EXCLUDE_DIR}",
        "--show-closures",
        cwd=_baseline.ROOT,
    )
    data = _tools._parse_xenon_json(stdout)
    threshold = _baseline.COMPLEXITY_RANKS.index(_baseline.XENON_MAX_ABSOLUTE)
    printed = False
    for file_path, blocks in sorted(data.items()):
        for block in blocks:
            rank = block.get("rank", "A")
            if _baseline.COMPLEXITY_RANKS.index(rank) <= threshold:
                continue
            print(f"    {file_path}:{block.get('lineno')} {block.get('type')} {block.get('name')} rank {rank}")
            printed = True
    if not printed:
        print(f"    xenon/radon reported no rank > {_baseline.XENON_MAX_ABSOLUTE} blocks on these files")


def print_loc_details(paths: list[Path], max_lines: int = 300) -> None:
    for path in paths:
        print(
            f"    {path.as_posix()}: {_baseline._line_count(_baseline.ROOT / path)} lines "
            f"(cap {max_lines}, slack {_baseline.LOC_SLACK})"
        )


DETAIL_PRINTERS: dict[str, Callable[[list[Path]], None]] = {
    "ruff": print_ruff_details,
    "mypy": print_mypy_details,
    "xenon": print_xenon_details,
    "loc": print_loc_details,
}
