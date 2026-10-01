from __future__ import annotations

from pathlib import Path

from pydantic import Field

from ..helper.config import FromPyProjectTomlConfig


class RatchetConfig(FromPyProjectTomlConfig):
    target_dir_rel_path: Path = Field(default=Path("src"), validation_alias="target")
    ratchet_data_folder_rel_path: Path = Path("ratchet")
    baseline_glob: str = "baseline*.json"

    loc_max_lines: int = Field(default=300, validation_alias="max-lines")
    loc_line_growth_slack: int = Field(default=5, validation_alias="line-growth-slack")

    mypy_coded_error_re: str = r": error: .*\[([\w-]+)\]\s*$"
    mypy_uncoded_error_re: str = r": error: "

    xenon_complexity_ranks: str = Field(default="ABCDEF", validation_alias="complexity-ranks")
    xenon_max_absolute: str = Field(default="B", validation_alias="xenon-max-absolute")

    exclude_dirs: list[str] = [
        "archive_not_used_trash",
    ]
    exclude_dir_regex: str = Field(default="archive_not_used_trash", validation_alias="exclude-dir")


ratchet_config: RatchetConfig = RatchetConfig.from_pyproject_toml("ratchet")
