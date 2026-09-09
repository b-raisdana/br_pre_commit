# Sync Skill Files

Bidirectional mirror of `SKILL.md` across `.claude/skills`, `.codex/skills`, `.devin/skills`, `.qoder/skills`, `.copilot/skills`, `.kiro/skills`, `.kilo/skills` (and `.github/git-commit/SKILL.md` for the `git-commit` skill only).

Wired in `.pre-commit-config.yaml` as `sync-skill-files` and runs when a `SKILL.md` is staged.

## How it works

1. **Detect from git (source of truth).** The skills that need attention are read from `git diff --cached --name-status` — additions, modifications, renames and staged deletions. Working-tree-only edits that are not staged are never silently overwritten.
2. **Sync the staged intent.** The single canonical staged version of a modified/added skill is propagated to every mirror (missing mirrors are created, stale clean mirrors are overwritten and staged). A staged deletion is propagated everywhere as a staged `git rm`.
3. **Verify by folder scan.** A full scan confirms every shared skill's mirrors are byte-identical. Missing mirrors with identical existing copies are created automatically (low risk). Genuine content conflicts — mirrors that already diverge with no single canonical staged version — are **not** auto-fixed; the hook prints exactly which agents diverge and the manual steps, then blocks the commit.

## Safety: safe auto-fix vs. manual

- **Safe (auto-fixed, staged, exit 0):** a single canonical staged version propagating to clean/missing mirrors; staged deletions; missing mirrors of an otherwise-identical skill. The developer is not interrupted for these.
- **Unsafe (exit 1, manual steps):** conflicting staged versions for one skill; a skill both staged-modified and staged-deleted; a mirror with uncommitted/untracked work that a sync would clobber; pre-existing committed divergence. Each is reported with the conflicting paths and a `cp`/`git rm` + re-stage recipe.

## Exclusions

Two mechanisms keep agent-specific skills from propagating:

### 1. Hardcoded skip list (`HARDCODED_SKIPS`)

Exact folder names in the Python `set` at the top of `sync-skill-files.py`:

```python
HARDCODED_SKIPS = {"use-aget-skills", "kilo-only-todo-discipline"}
```

Use this for legacy skills that were excluded before the naming convention existed, or for one-offs that don't fit the prefix pattern.

### 2. `{agent}-only-` prefix pattern

Any folder whose name starts with `<agent>-only-` is automatically excluded from cross-agent sync.

Examples: `kilo-only-todo-discipline`, `claude-only-review`, `codex-only-experimental`. This is the preferred convention for new agent-specific skills.

## Adding a new agent-specific skill

1. Create it under the agent's directory using the prefix:
   `mkdir -p .kilo/skills/kilo-only-my-skill`
2. Add `SKILL.md` inside it with the standard marker:
   `This skill is specifically designed for the Kilo agent. Do not propagate to other agent skill directories.`
3. The sync hook never copies it to the other agent directories.

## Adding a new shared agent

1. Add the agent slug to the `AGENTS` list in `sync-skill-files.py`.
2. Create `.<agent>/skills/` in the repo.
3. The sync loop includes it automatically.

## Dependency

`sync-skill-files.py` uses [GitPython](https://github.com/gitpython-developers/GitPython) via its `repo.git` raw-command interface (declared in `requirements-dev.txt`). The high-level `Repo.index.diff(...)` object API is deliberately **not** used: in gitpython 3.1.x it misreports staged deletions as additions, which would silently break delete detection.
