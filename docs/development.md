# Development and testing

Use `./start.sh` to develop and `./verify.sh all` to check the current source checkout.
Run commands from the repository root; both scripts also work by absolute path from
another directory. Verification exits nonzero if a requested check fails or is blocked.

## First-time setup

Install the development prerequisites in [releasing.md](releasing.md#local-development):
Python 3.12, uv, Node 22 with npm, pnpm 10 or Corepack, Rust stable, and Tauri's native
libraries. The scripts sync dependencies from the committed lockfiles. They do not install
system packages or change global package-manager configuration.

```sh
uv sync --project core --locked
corepack pnpm@10 --dir app install --frozen-lockfile
corepack pnpm@10 --dir app exec playwright install chromium
./verify.sh doctor
```

If you have pnpm installed, replace `corepack pnpm@10` with `pnpm`. Browser installation
is a separate first-time download; rerun it when the Playwright version changes.
`./verify.sh --help` lists the modes. Windows can invoke the Python entry point directly:
`uv run --project core --locked python scripts/verify.py quick`.

On Arch Linux, native testing additionally needs `xorg-server-xvfb`, `xorg-xauth`,
`xdotool`, `imagemagick`, and D-Bus (`dbus-run-session`). GTK 3, WebKitGTK 4.1, OpenSSL,
`pkg-config`, and the Rust/C build toolchain must also be available. `doctor` checks the
executables and library metadata. Install missing system packages yourself with your
normal package manager; verification never invokes sudo.

## Pick the relevant checks

| Command | What it exercises | What it does not establish |
| --- | --- | --- |
| `./verify.sh quick` (the default) | Python lint and tests, verification-harness contracts, frontend components, production frontend build, Rust formatting and tests | A rendered browser or native window; excludes tests marked models, network, or live |
| `./verify.sh browser` | Playwright UI workflows with a real Python core, local fixtures, and scripted model responses | Native Tauri dialogs/clipboard; real model quality |
| `./verify.sh desktop` | Linux native debug build and the actual `start.sh` launcher, real WebKit rendering, core connection, normal window close, child-process cleanup | A packaged installer; native dialog/clipboard interactions |
| `./verify.sh all` | All three layers, including independent layers after a failed check | Windows/macOS runtime behavior, model downloads, live providers |
| `./verify.sh doctor` | Tool discovery and Linux native library metadata | A successful build or runtime |

The first Rust build can take several minutes. Dependencies and build artifacts remain
local to the checkout and are reused on later runs. The native debug build embeds the
frontend and uses the source Python core; it omits packaged PyInstaller resources.
The launcher check also exercises Vite and the development startup path. Only one
verification run can own a checkout at a time, preventing simultaneous builds from
replacing files under a running test. Use a separate worktree for parallel work.

Browser tests use port 1421 by default and refuse to reuse another server; set
`BADSHOP_E2E_PORT` to choose another port. The launcher check uses
port 1422 (set `BADSHOP_DEV_PORT` to override), leaving the usual development port 1420
available for your app. A port conflict is a failure,
not a reason to kill an unrelated process.

## A private desktop for automation

No login-session DISPLAY is required on Linux. The native runner starts `Xvfb` with a
1600×1100 display and a private D-Bus session, forces the app to use X11, and puts its
settings, data, logs, and export directory in temporary folders. It only observes or
closes windows belonging to the process it started. It never drives your KDE session.

The native check waits for an actual window **and** an established renderer/core socket,
then captures a nonblank screenshot. It sends a normal window-close request and verifies
that the shell exits successfully and its children stop. Failure cleanup terminates only
the processes owned by the harness. Screenshots prove rendering, not that every control
works; browser workflow checks and native interactive checks cover those separately.

Windows and macOS installer/runtime validation remains in
[the native CI workflow](../.github/workflows/native-desktop.yml) and the
[release checklist](releasing.md#release-checks-needing-actual-environments). The local
`desktop` mode fails explicitly on unsupported platforms instead of claiming coverage.

## Evidence and diagnosis

Each invocation creates `artifacts/verification/<UTC timestamp>-<pid>/`, containing a log
for every command and `summary.json` with source revision/status, check statuses,
exit codes, and timings. Use
`--output /absolute/path` to choose a directory. Browser failures retain screenshots and
Playwright traces under `browser/`; native runs save `native.png`, `launcher.png`, and
matching app logs. Generated evidence is ignored by Git.

The runner prints the log location immediately and the final lines when a command ends.
For a long compilation, follow its log in another terminal. To inspect a browser trace:

```sh
corepack pnpm@10 --dir app exec playwright show-trace /path/to/trace.zip
```

Read the failed stage's log first. A missing executable, occupied port, build failure,
timeout, or blocked dependent stage must remain visible as a failure. Do not replace a
failed real check with a mock and call the workflow verified. After a fix, rerun the
failed layer and any other layer affected by the change.

## Acceptance criteria before implementation

Write a small task-specific checklist before changing behavior. These are the baseline
criteria for desktop work; identify which ones the task affects:

| User action | Expected result | Evidence |
| --- | --- | --- |
| Start from a source checkout with prerequisites installed | `./start.sh` prepares locked dependencies, opens a real window, and connects to the core | Native launcher smoke; first-install dependency resolution is separate from warm-cache timing |
| Import a local fixture image | Image appears in the viewer/attachments and the core records an artifact | Browser UI/core workflow; manually exercise the native picker when changing it |
| Run a deterministic tool | A completed timeline step and visible output appear | Browser workflow plus core tests |
| Edit and replay a step | Updated output and remapped downstream references persist | Session/core and browser workflow tests |
| Save and reopen | Artifacts, steps, and edits survive | Real project-file tests and browser workflows; native picker changes require native interaction |
| Cancel a dialog or encounter a failed save | Existing work survives and a useful error is shown | Component and browser tests, plus native interaction for platform changes |
| Close an unmodified window | Shell, core, and owned workers exit without survivors | Native smoke |
| Close with unsaved changes | Save/Discard/Cancel choices preserve the user's decision | Document-guard tests; manually check the native close path when changing it |

When changing file dialogs, drag/drop, clipboard, keyboard input, or keychain integration,
add a concrete native test or perform and record that interaction on the target platform.
The current native smoke does not claim those interactions. A useful completion report
states: changed behavior; commands and outcomes; evidence locations; unverified behavior.

## Isolated worktrees

Use one worktree per task and reuse it for follow-up fixes. An agent with a managed
worktree tool should use that tool. Otherwise, from this repository:

```sh
git worktree add ../badshop-my-task -b task/my-task HEAD
cd ../badshop-my-task
uv sync --project core --locked
corepack pnpm@10 --dir app install --frozen-lockfile
```

A new worktree contains the chosen commit, **not** the source checkout's uncommitted work.
If a task depends on those changes, preserve them in the original checkout and explicitly
copy the tracked binary diff and required untracked files into the worktree. Record that
inherited baseline before editing. Do not copy ignored virtualenvs, node_modules, target
folders, local credentials, or generated evidence. In particular, sharing an editable
Python environment can silently run code from the wrong worktree.

Review only your task's changes against that baseline. When returning changes to the
original checkout, first check that the affected files have not changed since the
snapshot; copy or apply only the task-owned changes. Never overwrite newer work. Remove
a worktree only after its work has been preserved, using `git worktree remove` (or the
managed tool), without force. Do not reset, stash, or commit unrelated work to tidy up.

## Expensive and live checks

These are deliberate opt-ins, separate from quick/browser/native development checks:

```sh
# Can download models/fonts; no real provider calls.
uv run --project core --locked pytest core/tests -q -m 'models and not network and not live'

# Network-dependent source/asset checks.
uv run --project core --locked pytest core/tests -q -m 'network and not live'
```

Real model/provider checks require the explicit environment switches documented in
`core/tests/test_live_provider.py` and `core/tests/test_cli_live.py`. Select the provider,
credentials, and cost allowance intentionally; none of the verification modes enables
them. For packaged binaries, OS keychains, AppImage, Flatpak, Windows, and macOS, follow
[releasing.md](releasing.md) and retain the CI evidence.
