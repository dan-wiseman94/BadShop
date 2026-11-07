# Private Arch Linux verification from Windows

This describes Dan's existing Windows/WSL setup. Check these paths before using
them on another host; do not change machine-wide configuration to match them.

- Distro: `archlinux` (WSL 2).
- Private toolchain: `/home/dan/.local/share/badshop-linux-test`.
- Launcher: `/home/dan/.local/share/badshop-linux-test/run`.
- The launcher supplies private Node, X11, library, and dependency-cache paths,
  then changes to its setup checkout. That checkout is not automatically the
  revision being developed in the current task.

## Prepare the task checkout

Read the current Windows revision/status and inspect the Linux repository and its
worktrees through the launcher. Create or reuse an isolated Linux worktree for
this task at the exact revision under test. Transfer missing commit objects with
Git fetch or a local bundle as appropriate; confirm the resulting HEAD.

Apply the relevant tracked binary diff and copy only needed untracked files.
Record the inherited baseline and verify the copied state. Do not copy `.venv`,
`node_modules`, Rust targets, credentials, caches, or another run's evidence.
Let locked dependency setup create a distinct environment in the Linux worktree.
Leave the setup checkout and unrelated worktrees intact.

## Run focused checks first

Use the minimum named test/file and affected end-to-end workflow selected under
the main skill. State the selection and purpose before execution. For a focused
Python check, replace the path and test selector below with the verified task values:

```powershell
wsl.exe -d archlinux --exec /home/dan/.local/share/badshop-linux-test/run bash -c 'cd -- "$1"; exec uv run --project core --locked pytest "$2" -q' _ /absolute/linux/worktree core/tests/test_file.py::test_name
```

Retain the command, revision, exit code, and log under artifacts/verification.
The main skill's start/end origin/main comparison also applies to the revision
transferred into this Linux worktree.

## Invoke broader harness checks only when justified

In PowerShell, replace the example path with the verified absolute Linux worktree
path and choose the mode only after explaining the broadening reason from the main skill:

```powershell
wsl.exe -d archlinux --exec /home/dan/.local/share/badshop-linux-test/run bash -c 'cd -- "$1"; exec ./verify.sh "$2"' _ /absolute/linux/worktree desktop
```

`quick` and `browser` use the same command with a different final argument. Passing
worktree and mode as positional arguments avoids interpolating paths into shell
code. An explicit output directory can be passed as one more argument:

```powershell
wsl.exe -d archlinux --exec /home/dan/.local/share/badshop-linux-test/run bash -c 'cd -- "$1"; exec ./verify.sh "$2" --output "$3"' _ /absolute/linux/worktree browser /absolute/linux/worktree/artifacts/verification/task-browser
```

Always change directory after the launcher for task-specific commands, including
focused pytest runs. Confirm revision and cwd before diagnosing a result as a
regression. Keep exported environment settings confined to that child run.

## Evidence and coverage

Use the harness's private Xvfb and D-Bus session for native automation with temporary
app data. Do not drive the logged-in KDE session. Retain Linux logs, screenshots,
traces, and `summary.json`; copy them into the Windows task's
`artifacts/verification/` when needed for accessible review, preserving provenance.

WSL debug checks do not replace the packaged installer workflow. Follow
`docs/releasing.md` for installer coverage and report unavailable platforms or
interactions explicitly. Keep the Linux worktree until its work and evidence are
preserved; remove it with Git's worktree command without force when no longer needed.

## Reusable preparation

Use scripts/wsl_task.py prepare from the Windows task checkout as documented in
docs/development.md. It transfers the revision and selected working changes,
preserves warm outputs, refuses unexpected Linux edits, and verifies a private
editable install. For warranted full runs on this PC use four Python workers or
two browser workers when supported, separate from CPU-heavy builds; diagnose
timing failures serially.
