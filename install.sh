#!/bin/sh
set -eu
tool_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=${1:-$(git rev-parse --show-toplevel)}
repo_root=$(CDPATH= cd -- "$repo_root" && pwd)
git_dir=$(git -C "$repo_root" rev-parse --absolute-git-dir)
hook="$git_dir/hooks/pre-commit"
{
    echo '#!/bin/sh'
    printf 'export BR_PRE_COMMIT_REPO_ROOT=%s\n' "$(printf %s "$repo_root" | sed "s/'/'\\''/g; s/^/'/; s/$/'/")"
    printf 'export BR_PRE_COMMIT_TOOL_ROOT=%s\n' "$(printf %s "$tool_root" | sed "s/'/'\\''/g; s/^/'/; s/$/'/")"
    cat <<'EOF'
if ! command -v wsl.exe >/dev/null 2>&1; then
    exec "$BR_PRE_COMMIT_TOOL_ROOT/run"
fi
export WSLENV="BR_PRE_COMMIT_REPO_ROOT/p:BR_PRE_COMMIT_TOOL_ROOT/p${GIT_INDEX_FILE:+:GIT_INDEX_FILE/p}${WSLENV:+:$WSLENV}"
exec wsl.exe -d Ubuntu-24.04 -- bash -lc '
    source ~/miniconda3/etc/profile.d/conda.sh &&
    conda activate tf &&
    cd "$BR_PRE_COMMIT_REPO_ROOT" &&
    exec "$BR_PRE_COMMIT_TOOL_ROOT/run"
'
EOF
} > "$hook"
chmod +x "$hook"
echo "Installed $hook -> $tool_root/run"
