#!/usr/bin/env sh
echo "Python: $(command -v python)"
$env:PYTHONPATH = 'C:\Code\XAAUSD-PAction-projectFolder\br_pre_commit/install'
exec python "$(dirname -- "$0")/install.py" "$@"
