from __future__ import annotations

from pathlib import Path

from pydantic import Field

from helper.config import FromPyProjectTomlConfig
from helper.paths import get_user_repo_path_from_env


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

    @property
    def baseline_dir(self):
        from config import br_pre_commit_config

        return (
            get_user_repo_path_from_env()
            / br_pre_commit_config.data_folder_rel_path
            / self.ratchet_data_folder_rel_path
        )


ratchet_config: RatchetConfig = RatchetConfig.from_pyproject_toml("ratchet")

# RatchetConfig = TypedDict(
#     "RatchetConfig",
#     {
#         "target": str,
#         "max-lines": int,
#         "line-growth-slack": int,
#         "complexity-ranks": str,
#         "xenon-max-absolute": str,
#         "exclude-dir": str,
#         "baseline-dir": str,
#     },
#     total=False,
# )

#
# TARGET = str(_SETTINGS["target"])
# COMPLEXITY_RANKS = str(_SETTINGS["complexity-ranks"])
# LOC_SLACK = int(_SETTINGS["line-growth-slack"])
# XENON_MAX_ABSOLUTE = str(_SETTINGS["xenon-max-absolute"])
# EXCLUDE_DIR = str(_SETTINGS.get("exclude-dir", "archive_not_used_trash"))
#
# MYPY_CODED_ERROR_RE = re.compile(r": error: .*\[([\w-]+)\]\s*$")
# MYPY_UNCODED_ERROR_RE = re.compile(r": error: ")
