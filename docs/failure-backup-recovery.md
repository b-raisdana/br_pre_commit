# Failure backup / recovery

`src/br_pre_commit/backup.py` and `src/br_pre_commit/recover.py` preserve and
restore a project's Git working state when a pre-commit hook fails. They are
the safety net between a red hook and lost staged work.

## Design summary

| Property | Backup (`backup.py`) | Recovery (`recover.py`) |
|---|---|---|
| Git state | **Read-only** — never touches `HEAD`, the index, `refs/stash`, or `refs/heads/` | **The only script allowed to** mutate shared git state |
| Concurrency | Safe to run concurrently with itself and with other git operations | Mutating steps are guarded by an advisory file lock so concurrent callers can detect each other |
| Trigger | Run automatically by the wrapper on any hook failure | Invoked explicitly by a human or agent |
| Failure mode | Per-file errors are recorded and the run continues | Stops at the first failed `git apply` and reports exactly which file failed |

Backup is intentionally non-mutating so it is safe to snapshot at any moment —
even mid-commit. Recovery is deliberate and opt-in, which is why it is the
only step that rewrites shared git state, and it asks the user for the
snapshot explicitly.

## backup.py — read-only snapshot

A pure-async snapshot (concurrent Git subprocesses for metadata +
content-addressed diffs, with thread-offloaded file writes so the event loop
is not blocked). It captures three categories of working state:

- **Staged** — `git diff --cached -- <path>` for each staged file.
- **Unstaged** — `git diff -- <path>` for each modified-but-unstaged file.
- **Untracked** — raw byte copy of each untracked file.

### Snapshot layout

Under `<repo>/logs/pre-commit/backup-patches/`:

```
logs/pre-commit/backup-patches/
  <branch>.<short_commit>/
    manifest.json
    staged/<rel-path>.<content-hash>.patch
    unstaged/<rel-path>.<content-hash>.patch
    untracked/<rel-path>
```

- The directory name is `<branch>.<short_commit>` (e.g.
  `feature/roundtrip.abc1234`).
- Patch filenames use a **7-hex CRC-32** content identifier so changed
  versions of the same file coexist; identical patches replace their prior
  copy and refresh its mtime (no duplicates, no stale copies).
- Untracked files are stored without a suffix (their content identifier is the
  path itself, relative to the snapshot root).
- `manifest.json` records branch, commit hash, timestamp, the snapshot path,
  and one entry per file describing its original path, stored path, and type
  (`patch` / `failed`).

Per-file error handling: if one file fails, it is recorded as `"failed"` in
the manifest and the snapshot continues with the rest — a single missing or
permission-denied file does not abort the whole backup.

A one-line summary is logged: snapshot path, staged/unstaged/untracked counts,
and total size in KB.

### When it runs

The wrapper runs `backup.py` in a **dedicated subprocess** whenever any
blocking job fails (non-zero exit). The snapshot directory is printed to
stdout and recorded under `snapshot_dir` in the JSON log entry
(`logs/pre-commit/pre-commit.log`).

## recover.py — restore from a snapshot

`recover.py` is the only script that touches shared git state. It reads the
snapshot's `manifest.json` (refusing to proceed if missing or malformed),
optionally checks out the snapshot's commit, then reapplies each category:

1. **Staged** — `git apply --cached` each `.patch` (with a preceding
   `git reset HEAD -- <path>` to clear conflicts cleanly).
2. **Unstaged** — `git apply` each `.patch`.
3. **Untracked** — raw byte copy back to the original path.

Mutating steps are wrapped in an advisory file lock at
`<repo>/.git/recover.lock` (`fcntl.flock`, 5-second default timeout) so
concurrent sensitive operations can detect each other. The lock is
**advisory, not mandatory** — it only protects callers that also check for it.

If any `git apply` fails (e.g. the working tree has diverged and the patch
context no longer matches), recovery **stops and reports exactly which file
failed and why** — partial recovery with a clear error beats silent full
failure. The snapshot directory is left on disk untouched after a run.

### CLI

```sh
python .tools/br_pre_commit/src/br_pre_commit/recover.py \
  --repo "$PWD" \
  --snapshot logs/pre-commit/backup-patches/<snapshot> \
  [--to-commit] \
  [--only staged|unstaged|untracked] \
  [--dry-run]
```

| Flag | Effect |
|---|---|
| `--repo` | Repository root (`--repo "$PWD"`). Required in practice, defaults to `.`. |
| `--snapshot` | Path to the snapshot directory (required). |
| `--to-commit` | Check out the snapshot's commit before reapplying — use when the working branch has moved on since the backup. |
| `--only` | Restrict reapply to one category (`staged`, `unstaged`, or `untracked`). |
| `--dry-run` | Print what would be done without touching anything. |

### Recovery workflow

```sh
# 1. Inspect the failing run's report and snapshot
cat logs/pre-commit/pre-commit.log   # find "snapshot_dir" for the failed run

# 2. Review the snapshot's manifest
cat logs/pre-commit/backup-patches/main.abc1234/manifest.json

# 3. (recommended) See what recovery would do, without touching anything
python .tools/br_pre_commit/src/br_pre_commit/recover.py \
  --repo "$PWD" \
  --snapshot logs/pre-commit/backup-patches/main.abc1234 \
  --dry-run

# 4. Restore
python .tools/br_pre_commit/src/br_pre_commit/recover.py \
  --repo "$PWD" \
  --snapshot logs/pre-commit/backup-patches/main.abc1234
```

### Tests

`tests/test_recover.py` exercises staged+unstaged round-trips, binary-file
round-trips, the content-hash coexistence/refresher behavior, untracked
round-trips, clear failure on a diverged tree, `--dry-run`, missing-manifest
refusal, `--only staged`, and `--to-commit` — all against throwaway git
repositories created with `git init`.

## See also

- The wrapper that triggers backup on failure:
  [concurrent-wrapper.md](concurrent-wrapper.md)
- Integration overview in the root README: [README.md](../README.md)
