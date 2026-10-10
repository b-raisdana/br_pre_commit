# Backup System

Full and patch snapshot creation and restore for pre-commit hook failures. Runs on every pre-commit run when a hook fails.

## Quick Start

On hook failure, snapshots are written to `logs/pre-commit/backup-patches/` in the target project. Restore with:

```sh
python -m src.backup.recover \
  --repo "$PWD" \
  --snapshot logs/pre-commit/backup-patches/<snapshot>
```

## What Gets Backed Up

Two types of snapshots on every pre-commit run:

| Type | Location | Contents |
|------|----------|----------|
| **Patch backups** | `logs/pre-commit/backup-patches/` | Git diffs for each **tracked** file that changed in the commit (staged + unstaged). Only modified tracked files appear here. |
| **Full backups** | `logs/pre-commit/full_backup/` | Complete copies of **text-based** files (tracked, unstaged, and untracked) that are **not excluded** by `full_backup_exclude_dir_regex`. Excluded files are **not backed up at all** (no patch, no full copy). |

## Configuration

Defined in `pyproject.toml` under `[tool.br_pre_commit.backup]`:

```toml
[tool.br_pre_commit.backup]
full_backup_exclude_dir_regex = '^(data|logs|archive_not_used_trash|\.[^/]+)$'
```

### How the Regex Works

The regex is matched against **each individual path part** (directory or filename) in the file's relative path. A file is excluded from full backup if **any** path part fully matches the regex.

Default regex breakdown:

| Pattern | Matches |
|---------|---------|
| `data` | Any directory named `data` at any depth |
| `logs` | Any directory named `logs` at any depth |
| `archive_not_used_trash` | Any directory with this exact name |
| `\.[^/]+` | Any hidden directory (starts with `.`, e.g. `.git`, `.venv`, `.mypy_cache`) |

### Customizing the Regex

Edit the regex in your project's `pyproject.toml`. Must be a valid Python regex pattern.

**Example: also exclude a `tmp` directory and `.pytest_cache`:**

```toml
[tool.br_pre_commit.backup]
full_backup_exclude_dir_regex = '^(data|logs|archive_not_used_trash|tmp|\.[^/]+)$'
```

**Example: allow `logs` to be fully backed up (remove from exclusion):**

```toml
[tool.br_pre_commit.backup]
full_backup_exclude_dir_regex = '^(data|archive_not_used_trash|\.[^/]+)$'
```

### What Gets Backed Up vs. Excluded

| File path | Excluded? | Reason |
|-----------|-----------|--------|
| `src/main.py` | No | No path part matches |
| `data/large.csv` | Yes | `data` matches |
| `logs/app.log` | Yes | `logs` matches |
| `.venv/lib/...` | Yes | `.venv` matches `\.[^/]+` |
| `src/.hidden/file.py` | No | Only `.hidden` would match, not `src` or `file.py` |

> **Note:** Patch backups (`backup-patches/`) are not affected by this regex — they always capture diffs for any tracked file that changed, regardless of its path. The regex only controls which files get a **full copy** in `full_backup/`.

## Per-Attempt Manifest

Every backup attempt writes a JSON manifest under `logs/pre-commit/backup-manifests/`, named after the human-readable timestamp (with milliseconds) of the attempt, e.g. `2026-10-09T14-21-15.167.json`.

It lists the absolute full path of every backup file produced by that attempt — staged patches, unstaged patches, untracked copies, and full backups — so files belonging to a single pre-commit/backup run can be located and restored together without scanning the whole `logs/pre-commit/` tree.

## Recovery

### Restore from Patch Backups (most common)

```sh
# Restore all categories (staged, unstaged, untracked)
python -m src.backup.recover \
  --repo "$PWD" \
  --snapshot logs/pre-commit/backup-patches/<snapshot>

# Restore only staged changes
python -m src.backup.recover \
  --repo "$PWD" \
  --snapshot logs/pre-commit/backup-patches/<snapshot> \
  --only staged

# Dry-run to preview what would happen
python -m src.backup.recover \
  --repo "$PWD" \
  --snapshot logs/pre-commit/backup-patches/<snapshot> \
  --dry-run
```

### Restore from Full Backups (excluded directories)

```sh
# Restore only full backups (files excluded from patch backup by regex)
python -m src.backup.recover \
  --repo "$PWD" \
  --snapshot logs/pre-commit/backup-patches/<snapshot> \
  --only full
```

### Full Recovery (checkout commit + restore)

```sh
# Checkout the snapshot's commit first, then restore
python -m src.backup.recover \
  --repo "$PWD" \
  --snapshot logs/pre-commit/backup-patches/<snapshot> \
  --to-commit
```

### Recovery Options

| Option | Description |
|--------|-------------|
| `--snapshot` | Path to snapshot directory (required) |
| `--repo` | Repository root (default: `.`) |
| `--to-commit` | Checkout the snapshot's commit before recovery |
| `--only` | Restore only one category: `staged`, `unstaged`, `untracked`, or `full` |
| `--dry-run` | Print what would be done without touching anything |

### Advisory Lock

Recovery uses an advisory file lock (`.git/recover.lock`) to prevent concurrent sensitive git operations. The lock times out after 5 seconds.

## How It Works Internally

### Snapshot Creation (`python -m src.backup`)

1. **Gather git state** — current branch, commit hash, staged/unstaged/untracked file lists
2. **Split by exclusion regex** — files matching `full_backup_exclude_dir_regex` go to full backup; others get patch backup
3. **Create patch backups** — `git diff --binary` for staged/unstaged files; copy untracked text files
4. **Create full backups** — copy excluded files + all tracked text files to content-addressed store
5. **Write manifest** — `manifest.json` in snapshot dir + per-attempt manifest in `backup-manifests/`

### Recovery (`python -m src.backup.recover`)

1. **Load manifest** from `snapshot_dir/manifest.json`
2. **Acquire advisory lock** (`.git/recover.lock`)
3. **Optional: checkout commit** if `--to-commit`
4. **Restore by category**:
   - `staged` — `git reset HEAD -- <file>` then `git apply --cached <patch>`
   - `unstaged` — `git apply <patch>`
   - `untracked` — copy file from snapshot
   - `full` — copy file from `full_backup/` content-addressed store
5. **Release lock**

## Content-Addressed Storage

Full backups use content-addressed filenames: `{stem}.{crc32_hash}.{ext}`. This means:
- Identical file content produces the same filename (deduplication)
- Multiple versions of the same file can coexist with different hashes
- No overwrite risk — each unique content gets a unique name

## Logs

- `logs/pre-commit/pre-commit.log` — JSON summary line per run with snapshot path
- `logs/pre-commit/pre-commit-runs/<timestamp>.log` — detailed per-hook output
- `logs/pre-commit/backup-manifests/<timestamp>.json` — per-attempt file listing
