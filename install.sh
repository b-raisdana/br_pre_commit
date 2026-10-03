#!/usr/bin/env sh

set -eu

BrPreCommitDir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
UserRepoDir="$(pwd)"

Python="${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python}"
Python="${Python:-$(command -v python || true)}"


echo "Python: $Python"
echo "br_pre_commit repository directory: $BrPreCommitDir"
echo "User repository directory: $UserRepoDir"

if [ -z "$Python" ] || [ ! -x "$Python" ]; then
  echo "ERROR: no usable Python interpreter; activate a virtual environment first." >&2
  exit 1
fi

# Run as a module from the repository root: src.install imports its siblings
# (src.helper.paths), which only resolve inside the src package.
cd "$BrPreCommitDir"

exec "$Python" -m src.install "$UserRepoDir" "$@"
