# 11 — Installer Zero Third-Party Dependencies Design

## Overview

The installer itself must require **no third-party Python packages**. It must run with a clean Python installation using only the standard library.

## Requirements

### Allowed: Python Standard Library Only

The installer may only import from these standard library modules (Python 3.9+):

```python
# Core
import argparse
import dataclasses
import json
import os
import pathlib
import platform
import re
import shutil
import stat
import subprocess
import sys
import textwrap
import typing
from typing import (Any, Callable, Dict, List, Optional, Tuple, Union,
                    Protocol, runtime_checkable)

# Filesystem
import fnmatch
import glob

# Text/Encoding
import codecs
import locale

# Time/Date
import datetime
import time

# Collections
import collections
import itertools
import functools
import operator

# Math/Random
import math
import random
import statistics

# Hashing
import hashlib
import hmac
import secrets

# Compression
import gzip
import tarfile
import zipfile

# Config
import configparser
import csv
```

### Forbidden: Third-Party Packages

The installer must **not** require or import:

| Package | Reason |
|---------|--------|
| `pip` | Use `python -m pip` via subprocess |
| `setuptools` | Not needed for installation |
| `wheel` | Not needed |
| `virtualenv` | Not needed |
| `click` | Use `argparse` |
| `typer` | Use `argparse` |
| `rich` | Use plain `print` / `textwrap` |
| `requests` | Use `urllib.request` if needed |
| `toml` / `tomli` | Use `configparser` or manual parsing |
| `PyYAML` | Not needed for installer |
| `colorama` | Use ANSI codes directly or skip |
| `tqdm` | Not needed |
| `packaging` | Not needed |
| `importlib_metadata` | Use `importlib.metadata` (3.8+) |

### Runtime Dependencies vs Installer Dependencies

| Category | Examples | Installer Concern? |
|----------|----------|-------------------|
| **Installer deps** | None allowed | ❌ Must be zero |
| **Runtime deps** | `pre-commit`, `ruff`, `mypy`, `pytest` | ✅ Checked at hook runtime (see 05) |

The installer **may check/install runtime dependencies** of `br_pre_commit`, but those are not dependencies of the installer itself.

## Design: Pure Standard Library Installer

### Argument Parsing — `argparse`

```python
def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="br_pre_commit.install",
        description="Install br_pre_commit Git hook",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("repo_path", nargs="?", default=".",
                        help="Path to Git repository (default: current directory)")
    parser.add_argument("--force", action="store_true",
                        help="Force reinstall even if hook appears current")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without making changes")
    parser.add_argument("--uninstall", action="store_true",
                        help="Remove the hook and restore backup")
    parser.add_argument("--verify-only", action="store_true",
                        help="Run gap analysis only, no installation")
    parser.add_argument("--version", action="version",
                        version="br_pre_commit installer 1.0.0")
    return parser
```

### TOML Parsing — Manual or `configparser`

For `.br-pre-commit.toml` if needed:

```python
# Simple TOML subset parser using stdlib only
def parse_simple_toml(content: str) -> dict:
    """Parse basic TOML (key = value, sections) without external deps."""
    import configparser
    # configparser handles basic INI-style, which covers simple TOML
    # For complex TOML, add minimal parser or require tomli at runtime only
    parser = configparser.ConfigParser()
    parser.read_string(content)
    return {s: dict(parser[s]) for s in parser.sections()}
```

Or use a minimal embedded TOML parser (few hundred lines) if needed.

### JSON — `json` (stdlib)

```python
import json

def read_json(path: Path) -> dict:
    return json.loads(path.read_text())

def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2))
```

### File Operations — `pathlib`, `shutil`, `os`

```python
from pathlib import Path
import shutil
import stat

def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

def copy_file(src: Path, dst: Path) -> None:
    shutil.copy2(src, dst)

def make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
```

### Process Execution — `subprocess`

```python
import subprocess

def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False  # Handle errors manually
    )
```

### Platform Detection — `platform`, `sys`

```python
import platform
import sys

def is_windows() -> bool:
    return sys.platform == "win32"

def is_posix() -> bool:
    return not is_windows()

def get_python_executable() -> str:
    return sys.executable
```

## Verification: No Third-Party Imports

```python
# Test script to verify installer has no external deps
import sys
import subprocess

def test_clean_install():
    """Run installer in a clean virtualenv to verify no external deps."""
    result = subprocess.run([
        sys.executable, "-m", "venv", "/tmp/test_venv"
    ], capture_output=True)

    python = "/tmp/test_venv/bin/python"

    # Should work without any pip installs
    result = subprocess.run([
        python, "-m", "br_pre_commit.install", "--verify-only", "."
    ], capture_output=True, text=True)

    assert result.returncode in (0, 1)  # 0=ok, 1=warnings, not ImportError
    assert "ModuleNotFoundError" not in result.stderr
    assert "ImportError" not in result.stderr

if __name__ == "__main__":
    test_clean_install()
    print("✓ Installer runs with zero third-party dependencies")
```

## Verification Checklist

- [ ] No `import pip`, `import setuptools`, `import wheel`
- [ ] No `import click`, `import typer`, `import rich`
- [ ] No `import requests`, `import toml`, `import tomli`
- [ ] No `import yaml`, `import colorama`, `import tqdm`
- [ ] `argparse` used for CLI
- [ ] `json` used for JSON
- [ ] `configparser` or manual parsing for TOML
- [ ] `pathlib`/`shutil`/`os` for files
- [ ] `subprocess` for process execution
- [ ] `platform`/`sys` for platform detection
- [ ] Runs in clean venv with no packages installed
- [ ] `pip check` on installer environment shows no deps
