# Sync Skill Files

Bidirectional mirror of `SKILL.md` across `.claude/skills`, `.codex/skills`, `.devin/skills`, `.qoder/skills`, `.copilot/skills`, `.kiro/skills`, `.kilo/skills` (and `.github/git-commit/SKILL.md` for the `git-commit` skill only).

Wired in `.pre-commit-config.yaml` as `sync-skill-files` and runs when a `SKILL.md` is staged.

## How it works

1. **Detect from git (source of truth).** The skills that need attention are read from `git diff --cached --name-status` — additions, modifications, renames and staged deletions. Working-tree-only edits that are not staged are never silently overwritten.
2. **Sync the staged intent.** The single canonical staged version of a modified/added skill is propagated to every mirror (missing mirrors are created, stale clean mirrors are overwritten and staged). A staged deletion is propagated everywhere as a staged `git rm`.
3. **Verify by folder scan.** A full scan confirms every shared skill's mirrors are byte-identical. Missing mirrors with identical existing copies are created automatically (low risk). Genuine content conflicts — mirrors that already diverge with no single canonical staged version — are **not** auto-fixed; the hook prints exactly which agents diverge and the manual steps, then blocks the commit.
4. **Remove empty skill directories.** Git does not track empty directories, so a staged deletion of a `SKILL.md` otherwise leaves an empty `<agent>/skills/<skill-name>/` folder behind. The hook sweeps all agent skill folders (and the `.github/git-commit` slot) and removes any directory that is completely empty. Only truly-empty directories are touched; anything still containing files is left alone. This is best-effort and never blocks the commit.

## Safety: safe auto-fix vs. manual

- **Safe (auto-fixed, staged, exit 0):** a single canonical staged version propagating to clean/missing mirrors; staged deletions; missing mirrors of an otherwise-identical skill. The developer is not interrupted for these.
- **Unsafe (exit 1, manual steps):** conflicting staged versions for one skill; a skill both staged-modified and staged-deleted; a mirror with uncommitted/untracked work that a sync would clobber; pre-existing committed divergence. Each is reported with the conflicting paths and a `cp`/`git rm` + re-stage recipe.

## Exclusions

How the sync hook decides a skill is agent-specific and must not propagate:

**Detection is purely folder-name based.** The hook never reads the contents of `SKILL.md` to make that decision. A skill is excluded from cross-agent sync when its *folder name* matches one of the two rules below. This is checked by `is_excluded()` in `src/sync_skills/core.py:38`, which is consulted at every point where a skill would otherwise be written to or verified across mirrors (`__main__.py:99,113,117`, `sync.py:125,145,231`).

Two mechanisms keep agent-specific skills from propagating:

### 1. Configurable skip list (`hardcoded-skips`)

Exact folder names configured in `pyproject.toml` under `[tool.br_pre_commit.sync_skills]`:

```toml
[tool.br_pre_commit.sync_skills]
hardcoded-skips = ["use-aget-skills", "kilo-only-todo-discipline"]
```

This replaces the previous hardcoded Python set. Use this for legacy skills that were excluded before the naming convention existed, or for one-offs that don't fit the prefix pattern.

The list is loaded at runtime from `sync_skills_config.hardcoded_skips` (see `src/sync_skills/config.py`).

### 2. `{agent}-only-` prefix pattern

Any folder whose name starts with `<agent>-only-` is automatically excluded from cross-agent sync. The check is:

```python
any(skill_dir.startswith(f"{a}-only-") for a in AGENTS)
```

Examples: `kilo-only-todo-discipline`, `claude-only-review`, `codex-only-experimental`. This is the preferred convention for new agent-specific skills.

> **Note:** the folder name must start with the prefix. Placing the agent name later in the name (e.g. `my-skill-kilo-only`) does **not** trigger exclusion — only a leading `<agent>-only-` prefix is recognized.

## Adding a new agent-specific skill

1. Create it under the agent's directory using the prefix:
   `mkdir -p .kilo/skills/kilo-only-my-skill`
2. Add `SKILL.md` inside it. The sync hook never copies it to the other agent directories purely because of the `kilo-only-` folder prefix — no content marker is required or inspected.
3. To make the intent self-documenting, you may include the marker line:
   `This skill is specifically designed for the Kilo agent. Do not propagate to other agent skill directories.`
   This is documentation only; it does not affect sync behavior.

## Managing interested agents (add / remove)

The set of agents whose `SKILL.md` files are mirrored lives in the `AGENTS`
list in `src/sync_skills/core.py`. Add or remove an agent slug there; the sync
loop picks it up on the next run automatically.

### Adding an agent

1. Add the agent slug to the `AGENTS` list in `src/sync_skills/core.py`:
   ```python
   AGENTS = ["claude", "codex", "devin", "qoder", "copilot", "kiro", "kilo", "myagent"]
   ```
2. Create the agent's skills directory in the repo:
   ```sh
   mkdir -p .myagent/skills
   ```
3. Stage the directory and run the hook once:
   ```sh
   git add .myagent/skills
   # edit or copy a SKILL.md, then:
   pre-commit run sync-skill-files --all-files
   ```
   The first sync creates the mirror slots for the new agent and propagates every
   existing shared skill into `.<agent>/skills/<skill>/SKILL.md`.

### Removing an agent

1. Remove the agent slug from the `AGENTS` list in `src/sync_skills/core.py`.
2. The agent's directory (`.myagent/`) is no longer touched by the sync loop.
   If you want it gone from the repo, delete the directory and commit the removal:
   ```sh
   git rm -r .myagent
   ```
   The hook will not complain about a missing mirror for a removed agent.

> **Note:** removing an agent slug from `AGENTS` does **not** delete its skills
> from the working tree — the sync loop only stops *writing* to that slot.

## Dependency

`src/sync_skills/__main__.py` runs git via a thin subprocess wrapper in
`../helper/git.py` (no third-party git library). The high-level
`Repo.index.diff(...)` object API is deliberately **not** used: in gitpython
3.1.x it misreports staged deletions as additions, which would silently break
delete detection.
