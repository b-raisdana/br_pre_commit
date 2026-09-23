#!/usr/bin/env sh

INSTALL_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

PYTHON="$(command -v python)"

echo "Python: $PYTHON"
echo "Install directory: $INSTALL_DIR"

if [ -z "${VIRTUAL_ENV:-}" ] && [ -z "${CONDA_PREFIX:-}" ]; then
    echo "No active virtual environment or Conda environment!"
    exit 1
fi

export PYTHONPATH="$INSTALL_DIR${PYTHONPATH:+:$PYTHONPATH}"

exec "$PYTHON" "$INSTALL_DIR/install.py" "$@"
