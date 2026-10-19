# Duplicate code reduction plan

Implementation status: priorities 1–4 are complete. Priority 5 was reviewed and deferred because the Git setup in backup recovery and skill synchronization tests differs in history, index, and environment requirements; combining those fixtures would obscure test behavior. The synchronous Git helper was merged into `src/helper/git.py` and `src/git_helper.py` was removed.

## Priority 1: consolidate repeated recovery copy flow — complete

`src/backup/recover.py:127-183` implements `_recover_untracked` and `_recover_full` with nearly identical loops. Both skip invalid/missing stored paths, support dry runs, create destination parents, copy bytes, log success, and collect/log failures. Their differences are category labels, entry type filtering, and source directory selection.

- Introduce one private helper parameterized by category, source directory, entries, and optional entry-type validation (or normalize validated entries before calling it).
- Preserve the untracked sentinel behavior (`stored_path == "None"`) and require `type == "full"` only for full-backup entries.
- Keep the public `recover` category dispatch unchanged. The patch restoration loop is a different operation because it applies Git patches and staged patches require `reset` plus `apply --cached`.
- Add/retain tests for missing files, dry-run behavior, nested destination creation, write errors, and category-specific filtering.

This is the lowest-risk, clearest removal of duplicated control flow.

## Priority 2: share ratchet analyzer orchestration — complete

`src/ratchet/tools.py:147-183` submits the same four current-state analyzers in `run_current_analyzers` and `_run_current_and_before_analyzers`. The second function repeats those submissions before adding three before-state analyzer runs.

- Extract a private helper that submits a requested set of analyzer calls to a supplied executor and gathers them in a stable, named result structure.
- Have the current-only path request four jobs and the comparison path request seven jobs, preserving concurrent startup and result types.
- Preserve that LOC is measured only for the current tree; the before-state comparison currently needs per-file mypy, Ruff, and Xenon data only.
- Keep executor worker counts/thread names intentional and covered by the existing concurrency tests.

This reduces copy/paste while making concurrency behavior easier to review; avoid an abstraction that hides which tools run against which tree.

## Priority 3: centralize Git process invocation where semantics match — complete

Git command construction and failure handling recur in `src/helper/git.py:29-102`, `src/git_helper.py:20-74`, `src/backup/recover.py:34-43`, `src/helper/paths.py:112-122`, `src/install.py:55-88`, and `src/sync_skills/resolve.py:32-40`. There is already an async Git wrapper, a synchronous legacy wrapper, and direct `check_output` calls.

- First map callers to the required semantics: synchronous/asynchronous execution, bytes/text output, whether hook Git environment variables must be stripped, whether `GIT_INDEX_FILE` must be retained, and the distinct exception types callers rely on.
- Consolidate duplicated root discovery and matching command execution behind a small shared synchronous primitive, then adapt higher-level wrappers to translate exceptions at their boundaries.
- Merged the synchronous helper API into `src/helper/git.py` and removed `src/git_helper.py`; synchronous calls keep the caller's Git environment, while async hook calls keep the existing environment scrubbing.
- Do not force installer confirmation prompts, recovery errors, or skill-sync staged-index behavior into one broad API. Keep environment policy explicit.
- Add focused tests for argv/cwd/env, bytes vs text, missing repository behavior, and exception translation before migrating each caller.

This is a larger multi-module cleanup. The common process setup is duplication, but treating all Git calls as interchangeable could change index isolation or public error behavior.

## Priority 4: unify CRC-32 content hash implementation after compatibility review — complete

Three content hash functions implement CRC-32 independently: `src/backup/common.py:22-24`, `src/br_pandera/content_hash.py:24-26`, and SHA-256 baseline naming at `src/ratchet/common.py:146-153`. The two CRC-32 implementations both return seven hex characters but use opposite ends of the eight-character CRC representation. Backup artifact names therefore cannot be changed casually. Ratchet uses SHA-256 and should remain separate because its content identity contract is different.

- Pick and document one seven-character CRC convention for new/shared use, then check whether stored backup filenames or output-dump filenames are a compatibility contract.
- If existing artifacts need stable lookup, preserve a legacy helper/reader or defer changing that domain; add shared tests for representative byte sequences and filename construction.
- Added `src/helper/content_hash.py` for the shared CRC-32 primitive; domain wrappers preserve their established first-seven and last-seven hex slices so existing filenames remain stable.
- Do not combine the ratchet SHA-256 baseline hash with CRC-32.

## Priority 5: reduce repeated test repository setup — deferred

`tests/unit/backup/test_recover.py` and `tests/unit/sync_skills/test_resolve.py` each create temporary Git repositories and configure related Git environment state. Several ratchet tests also repeat module monkeypatches for repository roots and analyzer behavior.

- Identify the shared setup steps and extract narrow fixtures/helpers into the nearest appropriate `conftest.py` (backup Git repo setup should stay separate from skill-sync index scenarios unless the setup is truly identical).
- Prefer reusable primitives such as `init_git_repo` and `make_git_env` over a large fixture that hides commits, staged state, or environment variables.
- Consolidate ratchet monkeypatch defaults only where tests share the same semantics; preserve per-test overrides and keep fixtures discoverable.

Test helpers reduce maintenance cost, but over-general fixtures can make Git state transitions harder to understand. This is lower priority than duplicated production control flow.

## Follow-up checks

For future changes to these areas:

1. Inspect its callers, tests, and documented behavior before editing.
2. Add or update focused tests for the preserved edge cases.
3. Run the focused test module, then the unit gate for Python changes.
4. Review the diff for changed filenames, exception types, Git environment, ordering, and logging behavior.

Similar-looking code intentionally left separate includes: patch recovery versus file copying; pandera/backup CRC naming until their seven-character conventions and existing artifacts are reconciled; ratchet SHA-256 baseline identifiers; and independent CLI output/error handling.
