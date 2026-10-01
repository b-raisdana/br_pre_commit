#!/usr/bin/env sh

INSTALL_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON="$(command -v python)"

echo "Python: $PYTHON"
echo "Install directory: $INSTALL_DIR"

# Run as a module from the repository root: src.install imports its siblings
# (src.helper.paths), which only resolve inside the src package.
cd "$INSTALL_DIR"
exec "$PYTHON" -m src.install "$@"
