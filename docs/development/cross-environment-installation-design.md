# Cross-environment installation design

Status: design guide for the current installers and the support contract that future installer work should preserve.

This guide separates three things that are often confused: where the project files live, which environment runs `git commit`, and which Python environment provides `br_pre_commit` and its tools. The editor used to modify files is separate; an editor on one side of the Windows/WSL boundary does not determine how a commit is executed.

## Terminology

### Linux native

A project and its Git client run in a normal Linux userland on a Linux filesystem. The supported entry point is `install/install.sh`, which installs a POSIX hook that directly executes `precommit_wrapper.py`.

### WSL

WSL runs a Linux userland on Windows, so its Python, shell, Git, and POSIX filesystem semantics are Linux semantics. It is part of the Linux runtime family for most wrapper code, but needs a separate support row because it adds Windows interop: `wsl.exe`, Windows drive mounts, `\\wsl$` and `\\wsl.localhost` paths, path translation, line-ending differences, executable-bit behavior, and the possibility of invoking Git from either side.

### Windows native

A project and its Git client run in Windows, normally on an NTFS path such as `C:\...`. The intended entry point is `install/install.ps1`, which installs a PowerShell hook that directly executes `precommit_wrapper.py`. Native Windows support still has runtime gaps described below.

### Execution environment

The execution environment is the process that runs the installed Git hook. It is not inferred from the editor, the operating system that last edited the file, or the operating system that created the checkout.

## Support matrix

| Project location | Commit environment | Installer/path | Runner | Python and tools | Current status |
|---|---|---|---|---|---|
| Linux filesystem | Linux Git | `install/install.sh` | `precommit_wrapper.py` (via Python) | Linux/POSIX environment | Supported |
| WSL distro filesystem | WSL Git | `install/install.sh` from WSL | `precommit_wrapper.py` (via Python) inside the configured distro | WSL Python environment | Supported |
| Windows filesystem | Windows Git | `install/install.ps1` | `precommit_wrapper.py` (via PowerShell) | Windows Python environment | Entry point exists; runtime gaps remain |
| WSL distro filesystem | Windows Git | Existing WSL hook | Mixed WSL/Windows handoff | Both sides may be required | Unsupported by default |
| Windows filesystem | WSL Git | Existing Windows hook | Mixed Windows/WSL handoff | Both sides may be required | Unsupported by default |
| Network, removable, or unusual filesystem | Either Git client | Explicit configuration required | Explicit runner | Explicit toolchain | Unsupported until tested |

The current scripts can sometimes make a mixed handoff appear to work. That is not a support guarantee. The hook contains absolute paths.

## Scenario decisions

### Linux-native project

Use `install/install.sh` and commit from Linux. The hook, Python interpreter, Git client, and project files all use the same Linux environment. This is the simplest supported mode.

### WSL-native project edited from Windows

A Windows editor is acceptable when it edits the WSL filesystem without changing the Git index or file metadata in incompatible ways. The supported commit path remains WSL Git: install the hook from WSL, run Git from WSL, and use the WSL Python environment and toolchain. A Windows editor does not make a Windows-side commit supported automatically. VS Code Remote WSL and similar editors should be treated as WSL execution when their terminal and Git operations run inside the distro.

### WSL install followed by a Windows commit

This is a cross-environment commit. The current hook may invoke `wsl.exe` from Windows and translate paths through `WSLENV`, but the result depends on the project path, Git client, distro, conda installation, executable bits, line endings, and the Windows-side PATH. It is not reliable enough to be the default contract.

The default policy should be **fail closed** for this combination: the hook should report that it was installed for WSL and must be run from WSL, with a short instruction for reinstalling for Windows. A project can opt into dual-mode support only after both runners, both toolchains, and both path directions are explicitly implemented and tested. The reverse case, Windows installation followed by a WSL commit, has the same policy.

### Windows-only project and `precommit_wrapper.py`

Keeping a single hook that directly executes `precommit_wrapper.py` via `python` is the right separation: the hook runs on the platform where Git executes it, using the `python` found in PATH. A Windows-only project can use the PowerShell hook without pretending that Windows has POSIX shell semantics.

For dual-mode projects, the generated hook should dispatch based on the current execution environment and an explicit installation capability record. It should not dispatch solely from the project path.

### Can the hook prevent Windows commits?

A hook can reject an unsupported commit when Git invokes it, but it cannot make a repository physically inaccessible from Windows. Windows Git may access a WSL filesystem through `\\wsl$` or `\\wsl.localhost`, and WSL can access Windows filesystems through `/mnt/...`. Git hooks can also be bypassed with `git commit --no-verify`.

Path detection can therefore support a warning or policy rejection, but it cannot prove that a Windows commit is impossible. The supported statement should be “Windows commits are unsupported for this installation”, not “the user cannot commit from Windows”.

## Python and dependency policy

### Current behavior

`precommit_wrapper/__main__.py` currently invokes bare `python` from `PATH`. The wrapper imports the `pre_commit` package. Skill synchronization uses GitPython, and project hooks invoke tools such as `ruff`, `mypy`, `pytest`, and `radon` from the active environment or `PATH`.

The installers do not currently create a virtual environment, select a Python interpreter, or install dependencies. The README asks users to install `pre-commit` in the environment used by Git hooks.

### System Python and `pip`

Using the system `python` and running `pip install` from an installer is technically possible for a simple project, but it should not be the universal default: system environments may be externally managed or require elevated permissions; `pip` may install into a different interpreter than the one used by the hook; Windows and WSL have separate package stores; dependency builds may require compilers or platform-specific wheels; an offline WSL distro may not have network access; and silently changing a global environment makes failures difficult to reproduce.

The preferred design is to select an explicit interpreter and install only into that interpreter with `python -m pip`. A project or tool virtual environment, or an explicitly configured conda environment, is preferable to an unqualified global install. The installer should validate the interpreter and required imports before writing a hook. System Python is acceptable only when the user explicitly selects it and it meets the supported version and dependency requirements.

The WSL installer currently hardcodes `Ubuntu-24.04`, `~/miniconda3/etc/profile.d/conda.sh`, and the `tf` environment. Those values are implementation assumptions, not a portable support contract. Future installers should make the distro, conda installation path, and environment name configurable, with a clear error when the selected environment is missing.

The project configuration targets Python 3.12 in `pyproject.toml`, but the launchers do not currently enforce a minimum version. The supported version range and authoritative dependency manifest should be made explicit before claiming cross-platform support.

## Path and environment detection

Detection should answer two independent questions: what environment is running the hook, and what kind of filesystem contains the project? Useful signals include `WSL_DISTRO_NAME`, `WSL_INTEROP`, `/proc/version`, the current process platform, and the project path. From Windows, a WSL-native path may appear as `\\wsl$\<distro>\...` or `\\wsl.localhost\<distro>\...`. From WSL, a Windows-native path commonly appears under `/mnt/<drive>/...`.

These checks classify the path; they do not establish whether another Git client can access it. A path-based check can warn that a Windows commit is outside the supported installation mode, reject a mixed-mode commit under a fail-closed policy, or choose a tested dual-mode runner when dual-mode support is enabled. It must not conclude that Windows access is impossible.

When a hook crosses environment boundaries, path variables must be translated explicitly. The installed hook sets only `BR_PRE_COMMIT_REPO_ROOT` and directly executes `precommit_wrapper.py` via `python`. UNC paths, substituted drives, spaces, Unicode, symlinks, case-sensitive paths, alternate index paths, Git worktrees, and Windows line-ending settings need defined behavior and tests.

The installed hook records absolute project and tool paths. Moving either checkout requires reinstalling the hook; the hook should not silently follow a stale path.

## Installer and hook contracts

The following behavior should be treated as a design requirement for future installer work:

1. Detect the current execution environment independently from the project path.
2. Select the matching runner and interpreter.
3. Validate the project root, tool root, Git repository, Python version, and required imports.
4. Preserve an existing hook or compose with it instead of silently replacing it. The current TODO in `docs/todo/install-detect-pre-commit-active.md` covers this gap.
5. Make repeated installation idempotent.
6. Record the installation mode and supported execution environments in the generated hook metadata.
7. Emit a useful diagnostic when a commit is attempted from an unsupported environment.
8. Avoid network access and global package mutation unless the user explicitly requests installation.
9. Define how Git for Windows executes the generated PowerShell hook, including shebang and execution-policy assumptions.
10. Define Windows-compatible project hook entries, including the POSIX-only `ratchet` launcher.

The current `install/install.sh` and `install/install.ps1` are not yet at parity. Both contain a WSL branch based on `wsl.exe`, both hardcode the same distro and conda environment, and they generate different hook formats. That divergence should be resolved before documenting mixed-mode behavior as supported.

## Cross-platform runtime gaps to clarify

These are the highest-priority foggy points that should be resolved or linked from this guide:

1. Exact supported Python versions and the authoritative dependency manifest.
2. Whether installers may modify system Python, and what happens when `pip` cannot write to it.
3. Configurable WSL distro, conda path, and conda environment.
4. The default policy for WSL-installed repositories committed from Windows, and the reverse.
5. Existing-hook preservation, composition order, and reinstall idempotency.
6. Windows-compatible locking for `recover.py`; it currently imports `fcntl.flock`, which is POSIX-only.
7. Windows process-group termination in the wrapper, which currently uses POSIX `os.killpg` on timeout or cancellation.
8. Path translation for repository, tool, index, UNC, symlink, and Unicode paths.
9. Tool availability and version policy for `pre-commit`, GitPython, `ruff`, `mypy`, `pytest`, `radon`, and project-specific hooks.
10. Filesystem semantics: CRLF/LF, executable bits, permissions, symlinks, case sensitivity, and file locks.
11. Whether logs and backup snapshots are shared, duplicated, or inaccessible when commits alternate between environments.
12. Ratchet target and exclusion assumptions, which currently couple behavior to particular project layouts.
13. Git worktrees, alternate `GIT_INDEX_FILE` values, submodules, and bare-repository behavior.
14. CI coverage for the same environment matrix; local hooks alone do not prove Windows or WSL behavior.

Lower-priority documentation gaps include hook-ID registry extensibility, recovery command ergonomics, log retention, and scheduled security/dependency checks.

## Acceptance matrix for implementation

Before marking cross-environment support as complete, test at least:

- native Linux install and commit;
- WSL-native install and commit;
- native Windows install and commit;
- Windows editor with WSL Git;
- WSL install followed by Windows Git;
- Windows install followed by WSL Git;
- project under `/mnt/c/...`;
- project under `\\wsl$\\<distro>\\...`;
- paths containing spaces and non-ASCII characters;
- custom WSL distro, conda path, environment, and virtual environment;
- missing Python, missing `pre-commit`, and missing project tools;
- existing hook, reinstall, and hook composition;
- CRLF/LF and executable-bit behavior;
- recovery on both POSIX and Windows;
- alternate Git index paths and worktrees;
- offline installation and no-global-python-mutation behavior.

Each mixed-mode test must state whether the expected result is a supported successful commit or a clear unsupported-mode rejection.
