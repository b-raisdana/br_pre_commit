# Hook installers

`install.sh` and `install.ps1` install the clone-local Git hook that connects a
consumer repository to this `br_pre_commit` checkout. The installers stay with
the source tree; they do not copy the Python implementation into the consumer.

## Installer files

| File | Use |
|---|---|
| [`install.sh`](install.sh) | POSIX shell installer for Linux, macOS, and WSL-based workflows. |
| [`install.ps1`](install.ps1) | PowerShell installer for native Windows workflows. |

Both installers accept the target repository root as their first argument. When
the argument is omitted, they use `git rev-parse --show-toplevel`.

## Install the hook

From the target project, run the installer that matches the environment used by
Git:

```sh
bash /path/to/br_pre_commit/install/install.sh "$PWD"
```

On Windows PowerShell:

```powershell
& "C:\path\to\br_pre_commit\install\install.ps1" `
    -RepoRoot "C:\path\to\your_project"
```

For a Git submodule, use the submodule path in your project, for example:

```sh
bash br_pre_commit/install/install.sh "$PWD"
```

The installer resolves the absolute paths of the target repository and the
`br_pre_commit` checkout, then writes `.git/hooks/pre-commit`. The generated
hook records those paths in `BR_PRE_COMMIT_REPO_ROOT` and directly executes
`precommit_wrapper` via `python -m`.

Re-run the installer after moving either checkout because the installed hook
contains absolute paths.

## Verify the installation

Run the generated hook directly:

```sh
.git/hooks/pre-commit
```

The default branch-protection setting blocks direct commits to `main`; verify on
a feature branch if the hook stops at that guard.

## Environment notes

Linux/WSL and native Windows use separate installers and runners. The current
scripts have environment-specific assumptions around the Python interpreter,
Git client, WSL distribution, and hook execution. See the
[cross-environment installation design](../docs/development/cross-environment-installation-design.md)
before using a mixed Windows/WSL workflow.
