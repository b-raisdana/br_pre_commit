# Hook installer

`install.sh` writes the clone-local `.git/hooks/pre-commit` shim that bridges
each consumer project to the shared `br_pre_commit` tool checkout. It does
**not** copy the tool into the project — the project keeps its own hook
selection, and the wrapper runs from its shared home.

## What the installer writes

`install.sh` records the absolute paths of both the target checkout and the
tool checkout, then writes a small POSIX sh shim to
`<repo>/.git/hooks/pre-commit`:

```sh
#!/bin/sh
export BR_PRE_COMMIT_REPO_ROOT='/abs/path/to/my_project'
export BR_PRE_COMMIT_TOOL_ROOT='/abs/path/to/br_pre_commit'
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
```

The shim then runs `run`, which launches the wrapper:

```sh
exec python "$tool_root/src/br_pre_commit/precommit_wrapper.py" "$@"
```

Recording absolute paths is what lets Git run the shared wrapper from any
working directory inside the repo.

## Installation

From the consumer project (which must be a Git repository, with `pre-commit`
installed in the environment Git hooks use):

```sh
bash .tools/br_pre_commit/install.sh "$PWD"
```

- The first argument is the target repository root (defaults to
  `git rev-parse --show-toplevel` if omitted).
- The tool root is derived from `install.sh`'s own location, so it works no
  matter where it is invoked from.
- The written shim is made executable (`chmod +x`).

### WSL vs. native

The shim detects whether it is running under WSL (`command -v wsl.exe`):

- **Native (Linux/macOS/WSL-native Git):** execs `run` directly in the
  current environment.
- **WSL Git invoking a Windows-side hook context:** re-execs through
  `wsl.exe -d Ubuntu-24.04` with a `bash -lc` that activates the `tf` conda
  environment and `cd`s to the repo root before running the wrapper.
  `WSLENV` exports the absolute paths into the WSL environment so the shim's
  recorded values survive the boundary hop.

Re-run `install.sh` after moving either checkout, because the installed hook
records absolute paths.

## Verify the integration

After installing, run the hook directly:

```sh
.git/hooks/pre-commit
```

On `main` this intentionally fails: direct commits to `main` are blocked by the
shared default (`wrapper.protected-branches = ["main"]`). Create a feature
branch before normal work:

```sh
git switch -c feature/initial-setup
.git/hooks/pre-commit
```

## Convenience launchers

The tool checkout ships shell launchers that mirror what the shim invokes.
Projects may copy them in as tracked convenience aliases:

| File | Purpose |
|---|---|
| `pre-commit` | `exec "$(git rev-parse --git-dir)/hooks/pre-commit"` — run the installed hook from anywhere in the repo (useful after `./pre-commit`). |
| `ratchet` | Execs `incremental_precommit/ratchet_check.py` — the incremental ratchet gate. Reference it as a local hook in `.pre-commit-config.yaml`. |
| `run` | `exec python "$tool_root/src/br_pre_commit/precommit_wrapper.py" "$@"` — the wrapper entry point the shim delegates to. |

Example local ratchet hook entry in a consumer `.pre-commit-config.yaml`:

```yaml
- repo: local
  hooks:
    - id: incremental-ratchet
      name: incremental ratchet
      language: system
      entry: .tools/br_pre_commit/ratchet
      pass_filenames: false
      files: ^app/.*\.py$
```

## What the project keeps vs. what is shared

| Owned by the consumer project | Owned by this shared tool |
|---|---|
| `.pre-commit-config.yaml` — enabled hooks and project-specific hook commands | the concurrent wrapper (`precommit_wrapper.py`) + config merge (`precommit_config.py`) |
| `.br-pre-commit/ratchet/baseline_*.json` — ratchet trend baselines | the incremental ratchet (`incremental_precommit/ratchet_check.py`) |
| optional `.br-pre-commit.toml` — overrides of shared defaults | defaults (`defaults.toml`) |
| — | failure backup (`backup.py`) + recovery (`recover.py`) |
| — | hook installer (`install.sh`) + launchers (`run`, `ratchet`, `pre-commit`) |

## See also

- The wrapper the shim delegates to: [concurrent-wrapper.md](concurrent-wrapper.md)
- The ratchet gate invoked via the `ratchet` launcher: [incremental-ratchet.md](incremental-ratchet.md)
