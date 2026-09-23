#!/usr/bin/env sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
br_pre_commit_dir=$(CDPATH= cd -- "$script_dir/../.." && pwd)
repo_root=$(CDPATH= cd -- "$br_pre_commit_dir/.." && pwd)
export BR_PRE_COMMIT_REPO_ROOT="$br_pre_commit_dir"

python="${BR_PRE_COMMIT_PYTHON:-}"
if [ -z "$python" ] && [ -x "$repo_root/.venv/bin/python" ]; then
    python="$repo_root/.venv/bin/python"
fi
if [ -z "$python" ]; then
    python="python"
fi

cd "$repo_root"
exec "$python" -m br_pre_commit.src.ratchet.baseline
