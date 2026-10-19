# Sync Skill Files

Consumer settings under `[tool.br_pre_commit.sync_skills]` select `agents` (physical folder slugs). For example, set `agents = ["agents", "claude", "kiro"]` when those separate mirrors are needed. Paths under unconfigured agent folders are ignored by staged-change classification. Set `github-git-commit = false` to disable classification and creation of the legacy `.github/git-commit/SKILL.md` slot. This repository configures only `agents` and disables the GitHub slot; configure consumer-specific settings in the consuming repository.

Bidirectional mirror of `SKILL.md` across configured physical folders. The defaults are `.agents/skills`, `.claude/skills` and `.kiro/skills`. The optional `.github/git-commit/SKILL.md` slot applies only to the `git-commit` skill and is enabled by default; set `github-git-commit = false` to disable it.

Wired in `.pre-commit-config.yaml` as `sync-skill-files` and runs when a `SKILL.md` is staged.

## How it works

1. **Detect from git (source of truth).** The skills that need attention are read from `git diff --cached --name-status` — additions, modifications, renames and staged deletions within configured slots. Working-tree-only edits that are not staged are never silently overwritten.
2. **Sync the staged intent.** The single canonical staged version of a modified/added skill is propagated to every mirror (missing mirrors are created, stale clean mirrors are overwritten and staged). A staged deletion is propagated everywhere as a staged `git rm`.
3. **Verify by folder scan.** A full scan of configured slots confirms every shared skill's mirrors are byte-identical. Missing mirrors with identical existing copies are created automatically. Divergent mirrors without a single canonical staged version are **not** auto-fixed; the hook reports the paths and manual steps, then blocks the commit.
4. **Remove empty skill directories.** The hook removes empty directories under configured agent skill folders and the `.github/git-commit` slot. Directories containing files are left alone. This cleanup is best-effort and does not block the commit.

## Safety: safe auto-fix vs. manual

- **Safe (auto-fixed, staged, exit 0):** a single canonical staged version propagating to clean/missing mirrors; staged deletions; missing mirrors of an otherwise-identical skill. The developer is not interrupted for these.
- **Unsafe (exit 1, manual steps):** conflicting staged versions for one skill; a skill both staged-modified and staged-deleted; a configured mirror with uncommitted/untracked work that a sync would clobber; divergent configured mirrors without a canonical staged version. Each is reported with the conflicting paths and a `cp`/`git rm` + re-stage recipe (or run the interactive resolver below).

## Interactive conflict resolution

When the hook blocks on a conflict, fix it interactively from the repository root:

```sh
python -m src.sync_skills.resolve
```

It lists every diverging mirror with a short preview, asks which version is canonical (or whether to delete a skill that is both staged-modified and staged-deleted), then applies the choice to all mirrors through the same safe write path as the hook — missing mirrors are created, clean mirrors are updated and staged, and mirrors with uncommitted/untracked edits are never clobbered. Skipping a skill (Enter) leaves it unresolved, is reported, and makes the command exit non-zero. It needs an interactive terminal; without one it prints the manual `cp`/`git rm` recipe instead.

If the shell lacks the `USER_REPO_ROOT` / `BR_PRE_COMMIT_REPO_ROOT` exports that the installed pre-commit hook provides (see `src/install.py`'s generated hook), the command discovers both roots from git, prints them, and asks `Do you confirm? [y/N]:` — the same interactive discovery `src/install.py` uses — before anything is read or written.

## Exclusions

How the sync hook decides a skill is agent-specific and must not propagate:

**Detection is purely folder-name based.** The hook never reads the contents of `SKILL.md` to make that decision. A skill is excluded from propagation and divergence checks when its *folder name* matches one of the two rules below. This is checked by `is_excluded()` in `src/sync_skills/core.py`.

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

The consuming repository's `[tool.br_pre_commit.sync_skills]` settings select physical mirror destinations. In the current implementation, the defaults in `src/sync_skills/config.py` are `agents = ["agents", "claude", "kiro"]` and `github-git-commit = true`. This repository overrides them in `pyproject.toml` with `agents = ["agents"]` and `github-git-commit = false`. `core.AGENTS` reads the configured list.

To add a destination, add its slug to `agents` and create its `.<agent>/skills/` folder. When staging is authorized, stage the canonical skill version and run `python -m pre_commit run sync-skill-files --all-files`; the hook populates supported slots and stages its changes.

To retire a destination, remove its slug from configuration before staging duplicate-file deletions. Removed slots are ignored by sync propagation, staged-change classification, and mirror verification, but configuration does not delete existing files. Preserve unique content before deleting redundant mirrors. Platforms that discover `.agents/skills/` directly share the `agents` slot. Disable `github-git-commit` before deleting the legacy special slot.

## Dependency

`src/sync_skills/__main__.py` runs git via a thin subprocess wrapper in
`../helper/git.py` (no third-party git library). The high-level
`Repo.index.diff(...)` object API is deliberately **not** used: in gitpython
3.1.x it misreports staged deletions as additions, which would silently break
delete detection.
