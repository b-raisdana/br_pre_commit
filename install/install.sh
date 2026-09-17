#!/usr/bin/env sh
echo "Python: $(command -v python)"
exec python "$(dirname -- "$0")/install.py" "$@"
