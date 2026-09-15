# 10 — Installer Python Compatibility Design

## Overview

The installer must support Python ≥ 3.9 with the goal of remaining compatible through Python 3.14+. Do not use syntax or APIs introduced after Python 3.9.

## Supported Python Versions

| Version | Status | Notes |
|---------|--------|-------|
| 3.9 | Minimum supported | Baseline for all syntax/APIs |
| 3.10 | Supported | Pattern matching available but not used |
| 3.11 | Supported | `tomllib`, `ExceptionGroup` available but not used |
| 3.12 | Supported | `f-string` improvements available but not used |
| 3.13 | Supported | Target for forward compatibility |
| 3.14 | Planned | Target for forward compatibility |

## Syntax Constraints

### Allowed (Python 3.9+)

```python
# Type hints with | union (3.10+) — use typing.Union instead
from typing import Union, Optional, List, Dict, Tuple

# Dataclasses
from dataclasses import dataclass

# pathlib
from pathlib import Path

# f-strings (3.6+)
f"Value: {value}"

# Walrus operator (3.8+)
if (n := len(items)) > 0: ...

# Pattern matching (3.10+) — AVOID, use if/elif
# match x: case 1: ...

# tomllib (3.11+) — AVOID, use tomli or manual parsing
# import tomllib

# ExceptionGroup (3.11+) — AVOID
# except* ValueError: ...

# Self type (3.11+) — AVOID, use typing_extensions or string annotation
# from typing import Self
```

### Disallowed (Post-3.9)

| Feature | Introduced | Alternative |
|---------|------------|-------------|
| `X | Y` union syntax | 3.10 | `Union[X, Y]` |
| `match`/`case` | 3.10 | `if`/`elif`/`else` |
| `tomllib` | 3.11 | `tomli` (backport) or manual |
| `ExceptionGroup` / `except*` | 3.11 | Regular exceptions |
| `Self` type | 3.11 | `"Self"` string annotation |
| `typing.TypeAlias` | 3.10 | `TypeAlias = ...` |
| `str.removeprefix` | 3.9 | OK (3.9+) |
| `str.removesuffix` | 3.9 | OK (3.9+) |
| `zoneinfo` | 3.9 | OK (3.9+) |
| `graphlib` | 3.9 | OK (3.9+) |

## Standard Library Modules Available in 3.9+

```python
# Core - always available
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

# Process/Execution
import signal  # POSIX

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

# Network/URL (if needed)
import urllib.parse
import urllib.request

# Hashing/Crypto
import hashlib
import hmac
import secrets

# Compression/Archives
import gzip
import tarfile
import zipfile

# Config/Serialization
import configparser
import csv
# import tomllib  # 3.11+ only - use tomli backport if needed
```

## Version Detection and Enforcement

```python
# In installer entry point
import sys

MIN_VERSION = (3, 9)
MAX_TESTED_VERSION = (3, 13)

def check_python_version() -> None:
    current = sys.version_info[:2]
    if current < MIN_VERSION:
        sys.exit(
            f"br_pre_commit installer requires Python >= {'.'.join(map(str, MIN_VERSION))}, "
            f"found {'.'.join(map(str, current))} ({sys.executable})"
        )
    if current > MAX_TESTED_VERSION:
        # Warning only - don't fail on newer Python
        print(f"WARNING: Python {'.'.join(map(str, current))} is newer than "
              f"max tested version {'.'.join(map(str, MAX_TESTED_VERSION))}. "
              f"Proceeding anyway.", file=sys.stderr)
```

## Forward Compatibility Strategy

1. **Use only 3.9+ APIs** — Avoid version-specific features
2. **Prefer stable stdlib modules** — `argparse`, `dataclasses`, `pathlib`, `subprocess`
3. **Graceful degradation** — If a newer API exists, use the older compatible one
4. **Explicit version checks** — Fail clearly if Python < 3.9
5. **Test on multiple versions** — CI matrix: 3.9, 3.10, 3.11, 3.12, 3.13

## Type Hinting Style

```python
# Use typing module imports (compatible with 3.9)
from typing import List, Dict, Optional, Union, Tuple, Callable, Any

# Use string annotations for forward references
def process(items: "List[Item]") -> "Result": ...

# Dataclasses for structured data
from dataclasses import dataclass

@dataclass
class Config:
    repo_root: Path
    tool_root: Path
    hooks: List[str]
    timeout: int = 30
```

## Verification Checklist

- [ ] No `X | Y` union syntax (use `Union[X, Y]`)
- [ ] No `match`/`case` statements
- [ ] No `tomllib` import (use `tomli` or manual)
- [ ] No `ExceptionGroup` / `except*`
- [ ] No `Self` type (use string annotation)
- [ ] No `typing.TypeAlias`
- [ ] Minimum version check at entry point
- [ ] Warning (not error) for Python > max tested
- [ ] CI tests on 3.9, 3.10, 3.11, 3.12, 3.13
- [ ] `mypy --python-version 3.9` passes
- [ ] All imports available in 3.9 stdlib
