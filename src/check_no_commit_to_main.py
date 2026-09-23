from __future__ import annotations

import subprocess

from helper.paths import get_user_repo_path_from_env
from precommit_wrapper.__main__ import _branch_protection_result


def main() -> int:
    repo_root = get_user_repo_path_from_env()
    branch = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    result = _branch_protection_result(branch)
    if result is None:
        return 0
    print(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
