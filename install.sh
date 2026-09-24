#!/usr/bin/env sh

INSTALL_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON="$(command -v python)"

echo "Python: $PYTHON"
echo "Install directory: $INSTALL_DIR"

exec "$PYTHON" "$INSTALL_DIR/src/install.py" "$@"
