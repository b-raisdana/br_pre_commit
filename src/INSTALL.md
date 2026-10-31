# Hook installers

`../install.sh` and `../install.ps1` install the clone-local Git hook that connects a
consumer repository to this `br_pre_commit` checkout. The installers stay with
the source tree; they do not copy the Python implementation into the consumer.

## Installer files

| File | Use |
|---|---|
| [`../install.sh`](../install.sh) | POSIX shell installer for Linux, macOS, and WSL-based workflows. |
| [`../install.ps1`](../install.ps1) | PowerShell installer for native Windows workflows. |

Run the installers from the target repository root with its virtual environment
active. The POSIX script accepts the target root as its first argument; the
PowerShell script uses the current directory. If omitted, the POSIX script uses
the current directory.

## Install the hook

From the target project, run the installer that matches the environment used by
Git:

```sh
bash /path/to/br_pre_commit/install.sh "$PWD"
```

On Windows PowerShell (run from the target repository root):

```powershell
Set-Location C:\path\to\your_project
& "C:\path\to\br_pre_commit\install.ps1"
```

The installer requires the packages in `../requirements.txt`, asks you
to confirm the target and tool repository roots, writes the hook under the
target's Git metadata, and merges `incremental-ratchet` into the target's
`.pre-commit-config.yaml` if it is missing. If a hook already exists, it asks
before replacing it; `--force` skips that prompt.

## Self-hosting

To install checks for `br_pre_commit` itself, create a Python 3.12+ virtual
environment in the repository root and install its requirements:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
./install.sh "$PWD"
```

On Windows, activate `.venv\Scripts\Activate.ps1`, install the same
requirements, and run `.\install.ps1` from the repository root. Confirm the
same root for both prompts. Then switch to a feature branch and run
`git hook run pre-commit`; the default branch guard blocks `main`, `develop`,
and `uat`.

If this checkout is a submodule, installing from inside it configures the
submodule's Git metadata. It does not replace the parent repository's hook;
install that separately from the parent root.

The installer derives both repository roots from Git and sets `USER_REPO_ROOT`
and `BR_PRE_COMMIT_REPO_ROOT`; no manual environment setup is needed. The
generated hook records both absolute paths and executes `precommit_wrapper` via
`python -m`.
Re-run the installer after moving either checkout because the installed hook
contains absolute paths.

## Verify the installation

Run the generated hook through Git:

```sh
git hook run pre-commit
```

The default branch-protection setting blocks direct commits to `main`; verify on
a feature branch if the hook stops at that guard.

## Environment notes

Linux/WSL and native Windows use separate installers and runners. The current
scripts have environment-specific assumptions around the Python interpreter,
Git client, WSL distribution, and hook execution. See the
[cross-environment installation design](../docs/development/cross-environment-installation-design.md)
before using a mixed Windows/WSL workflow.
