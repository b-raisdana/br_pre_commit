"""Baseline management for the incremental pre-commit ratchet.

Handles content-addressed baseline storage: JSON files named by SHA-256 hash of their
sorted, indented content. Multiple baselines are merged (union of keys, minimum value kept)
and consolidated into a single file on each run. This module knows nothing about linters
or touched files — only dict[str, int] baselines and their persistence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(os.environ.get("BR_PRE_COMMIT_REPO_ROOT", Path.cwd())).resolve()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from precommit_wrapper.config import ratchet_settings  # noqa: E402

_SETTINGS = ratchet_settings()
BASELINE_DIR = ROOT / ".br-pre-commit" / "ratchet"
BASELINE_GLOB = "baseline*.json"
TARGET = str(_SETTINGS["target"])
COMPLEXITY_RANKS = str(_SETTINGS["complexity-ranks"])
LOC_MAX_LINES = int(_SETTINGS["max-lines"])
LOC_SLACK = int(_SETTINGS["line-growth-slack"])
XENON_MAX_ABSOLUTE = str(_SETTINGS["xenon-max-absolute"])
EXCLUDE_DIR = str(_SETTINGS.get("exclude-dir", "archive_not_used_trash"))

MYPY_CODED_ERROR_RE = re.compile(r": error: .*\[([\w-]+)\]\s*$")
MYPY_UNCODED_ERROR_RE = re.compile(r": error: ")


def _excluded(path: Path) -> bool:
    """Return True when ``path`` lives under the configured exclude directory."""
    return EXCLUDE_DIR in path.parts


def _tool_of(key: str) -> str:
    return key.split(":", 1)[0]


def _line_count(path: Path) -> int:
    return sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))


def load_json(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return {str(k): int(v) for k, v in data.items()}
    except json.JSONDecodeError as e:
        log.exception(
            f"load_json json.loads({path}.read_text()) failed with JSONDecodeError:" + str(e),
        )
        raise e
    except Exception as e:
        log.exception(
            f"load_json json.loads({path}.read_text()) failed Generally:" + str(e),
        )
        raise e


def find_baseline_files() -> list[Path]:
    return sorted(BASELINE_DIR.glob(BASELINE_GLOB))


def merge_baselines(baselines: list[dict[str, int]]) -> dict[str, int]:
    """Merge multiple baselines: union of keys, minimum value kept."""
    merged: dict[str, int] = {}
    for baseline in baselines:
        for key, value in baseline.items():
            if key not in merged:
                merged[key] = value
            else:
                merged[key] = min(merged[key], value)
    return dict(sorted(merged.items()))


def compute_new_baseline(old_baseline: dict[str, int], current_counts: dict[str, int]) -> dict[str, int]:
    """Compute ratcheted baseline: for each key, keep the minimum of old and current."""
    result: dict[str, int] = {}
    for key in set(old_baseline) | set(current_counts):
        old_val = old_baseline.get(key, float("inf"))
        current_val = current_counts.get(key, 0)
        result[key] = int(min(old_val, current_val))
    return dict(sorted(result.items()))


def baseline_content_hash(baseline: dict[str, int]) -> str:
    """SHA-256 of JSON-serialized baseline (sorted keys, indented), truncated to 8 hex chars."""
    content = json.dumps(baseline, indent=2, sort_keys=True) + "\n"
    return hashlib.sha256(content.encode()).hexdigest()[:8]


def baseline_filename(baseline: dict[str, int]) -> str:
    return f"baseline_{baseline_content_hash(baseline)}.json"


def write_baseline_file(baseline: dict[str, int]) -> Path:
    path = BASELINE_DIR / baseline_filename(baseline)
    path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
    subprocess.run(["git", "add", str(path)], cwd=ROOT, check=False)
    return path


def load_and_consolidate_baselines() -> dict[str, int]:
    """Load all baseline files, merge them, and consolidate to a single file if >1 existed."""
    files = find_baseline_files()
    if not files:
        return {}
    baselines = [load_json(f) for f in files]
    merged = merge_baselines(baselines)
    if len(files) > 1:
        for f in files:
            f.unlink()
        write_baseline_file(merged)
        for f in files:
            subprocess.run(["git", "add", "--", str(f)], cwd=ROOT, check=False)
    return merged


def run(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    return result.stdout


def run_output(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    return result.stdout + result.stderr
