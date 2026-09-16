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
exec "$BR_PRE_COMMIT_TOOL_ROOT/run"
EOF
} > "$hook"
chmod +x "$hook"
echo "Installed $hook -> $tool_root/run"
