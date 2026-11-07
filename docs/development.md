# Development and testing

On Windows, follow the [source setup](windows.md#run-from-source) and double-click
`start.cmd`. On Linux and macOS, use `./start.sh`. Run the checks below from the repository
folder. Verification exits nonzero if a requested check fails or is blocked.

## First-time setup

Install the development prerequisites in [releasing.md](releasing.md#local-development):
Python 3.12, uv, Node 22 with npm, pnpm 10 or Corepack, Rust stable, and Tauri's native
libraries. The scripts sync dependencies from the committed lockfiles. They do not install
system packages or change global package-manager configuration.

Windows PowerShell:

```powershell
uv sync --project core --locked
pnpm.cmd --dir app install --frozen-lockfile
pnpm.cmd --dir app exec playwright install chromium
uv run --project core --locked python scripts/verify.py doctor
```

Linux and macOS:

```sh
uv sync --project core --locked
corepack pnpm@10 --dir app install --frozen-lockfile
corepack pnpm@10 --dir app exec playwright install chromium
./verify.sh doctor
```

If you have pnpm installed, replace `corepack pnpm@10` with `pnpm`. Browser installation
is a separate first-time download; rerun it when the Playwright version changes.
`./verify.sh --help` lists the modes. The private-display `desktop` and `all` checks require Linux.

On Arch Linux, native testing additionally needs `xorg-server-xvfb`, `xorg-xauth`,
`xdotool`, `imagemagick`, and D-Bus (`dbus-run-session`). GTK 3, WebKitGTK 4.1, OpenSSL,
`pkg-config`, and the Rust/C build toolchain must also be available. `doctor` checks the
executables and library metadata. Install missing system packages yourself with your
normal package manager; verification never invokes sudo.

## Pick the relevant checks

Start with the smallest test selection covering the changed behavior. State what it
checks before running it. Documentation-only changes need no application tests;
test deletions need collection and lint checks. Do not rebuild installers for test or
documentation changes.

From the repository root (use `pnpm.cmd` instead of `pnpm` in Windows PowerShell):

```sh
# One Python regression, or omit ::test_name to run its file.
uv run --project core --locked pytest core/tests/test_sheets.py::test_invalid_grid_creates_no_partial_output_artifacts -q

# One component regression; omit -t to run the affected file.
pnpm --dir app exec vitest run tests/session-actions.test.tsx -t "Cancel"

# One real browser/core journey.
pnpm --dir app exec playwright test e2e/project-journey.spec.ts --grep "manual editing"

# Collect without executing; unit/integration markers do not change the default suite.
uv run --project core --locked pytest core/tests --collect-only -q -m unit
pnpm --dir app exec vitest list --json
```

Add the affected end-to-end workflow when a feature crosses the UI/core boundary.
Broaden only when a shared fixture or dependency changes, a failure or coverage gap
requires it, or release validation explicitly calls for it. For example, changing the
shared browser/core fixture justifies the browser suite, but not a native rebuild.
Once the relevant checks pass, stop unless another edit changes their inputs.

The broader verification modes below remain available for those explicit cases.
They are not the default validation for each edit. The [test suite review](test-suite-review.md)
records which unit cases were removed and which integration coverage was preserved.

| Command | What it exercises | What it does not establish |
| --- | --- | --- |
| `./verify.sh quick` (explicit broad run) | Python lint and tests, verification-harness contracts, frontend components, production frontend build, Rust formatting and tests | A rendered browser or native window; excludes tests marked models, network, or live |
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

For a focused browser run with the verification summary, use
`./verify.sh browser --browser-test e2e/project-journey.spec.ts`. Repeat the flag
for additional Playwright file patterns. The summary labels this `browser-focused`.

When a full local run is warranted, `./verify.sh quick --core-workers 4` distributes
the offline Python suite by test file, and `./verify.sh browser --browser-workers 2`
runs the full Playwright suite with two workers. Both flags also work with `all`.
Run parallel tests apart from CPU-heavy builds. Omit the flags for serial execution
when diagnosing timing-sensitive failures or running with limited memory. The PR
and release commands use the existing full-suite defaults.

The verification runner selects available private browser and launcher ports; use
BADSHOP_E2E_PORT or BADSHOP_DEV_PORT to override them. Direct Playwright commands
use a worktree-derived port and retain strict binding.
A port conflict is a failure,
not a reason to kill an unrelated process.

## A private desktop for automation

No login-session DISPLAY is required on Linux. The native runner starts `Xvfb` with a
1600×1100 display and a private D-Bus session, forces the app to use X11, and puts its
settings, data, logs, and export directory in temporary folders. It only observes or
closes windows belonging to the process it started. It never drives your KDE session.

The native check waits for an actual window **and** a renderer receipt after
authentication, loaded session/provider data, a successful tool-catalog RPC, and
a paint opportunity. It then captures a nonblank screenshot. The receipt is enabled
only by the isolated harness and is retained beside the screenshot as .ready.json.
It sends a normal window-close request and verifies
that the shell exits successfully and its children stop. Failure cleanup terminates only
the processes owned by the harness. Screenshots prove rendering, not that every control
works; browser workflow checks and native interactive checks cover those separately.

Windows and macOS installer/runtime validation remains in
[the native CI workflow](../.github/workflows/native-desktop.yml) and the
[release checklist](releasing.md#release-checks-needing-actual-environments). The local
`desktop` mode fails explicitly on unsupported platforms instead of claiming coverage.

## Evidence and diagnosis

Each `verify` invocation creates `artifacts/verification/<UTC timestamp>-<pid>/`, containing a log
for every command and `summary.json` with source revision/status, check statuses,
exit codes, and timings. Use
`--output /absolute/path` to choose a directory. Browser failures retain screenshots and
Playwright traces under `browser/`; native runs save `native.png`, `launcher.png`, and
matching app logs. Generated evidence is ignored by Git.

Direct Playwright commands write failure screenshots, traces and core logs to
`artifacts/verification/playwright/<run>/`. Every test starts an isolated real core and the
fixtures reject unhandled browser exceptions. The project journeys verify actual image
bytes, replayed dependencies, save/reopen in a fresh process, collision-safe export and
recovery after a damaged project fails to open. They use browser dialog fallbacks; native
file pickers and installers still need the platform checks described below.

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


## Focused checks with retained evidence

Running ./verify.sh without a mode displays help and does not start a suite.
Focused modes retain logs, timings, revision/content fingerprints, the checkout
lock, and process cleanup. No matched/executed tests is a failure, including a
title filter that skips every test. Counts record skipped cases separately.

    ./verify.sh python --python-test core/tests/test_sheets.py::test_invalid_grid_creates_no_partial_output_artifacts
    ./verify.sh component --component-test tests/session-actions.test.tsx --test-name Cancel
    ./verify.sh browser --browser-test e2e/project-journey.spec.ts --test-name "manual editing"

Repeat the test flag for additional selections. Focused browser runs use the real
Vite/core journey without an unrelated production build. Run type/build checks
separately when required. Frontend modes prepare locked dependencies; Python mode
does not install frontend dependencies. Use --output for an explicit evidence
folder, preserving previous runs with unique directories.

## Task baseline and handoff

Use the isolated task worktree. These commands report overlap without merging,
rebasing, resetting, or changing another worktree.

    python scripts/task.py start --accept "Save/reopen preserves the edited output"
    python scripts/task.py finish

Start fetches origin/main, records HEAD and inherited content hashes, and inspects
other local worktrees. Finish fetches again, reports upstream changes, task overlap
and unmerged local worktree overlap, and compares evidence fingerprints with current
inputs. A failed fetch exits nonzero and remains unverified. Overlap and older
evidence require review, not automatic retesting. Remote unpushed work is outside
this local inventory. Reports live in artifacts/verification/task/. Use --record
for another baseline location. An existing start record cannot be replaced.

## Prepare a Linux task from Windows

The helper uses the existing archlinux private toolchain, installs no system
packages, and does not alter the setup checkout.

    python scripts/wsl_task.py prepare --target /home/dan/.local/share/badshop-linux-test/worktrees/my-task --include scripts/my_new_file.py

It transfers HEAD through a Git bundle plus all tracked working changes. Explicit
--include paths select relevant untracked files/directories; omitted paths are
reported. Ignored dependencies, credentials directories, and symlinks are not copied.
A private virtualenv is synced from the lockfile and its badshop import must resolve
inside that worktree. Follow-up runs reuse the worktree and warm compiled outputs.
An active verification lock, unexpected Linux edits, or a changed HEAD cause refusal rather than reset. Preserve
artifacts/verification/wsl-sync.json for change detection. Review wsl-ready.json for
the revision and suggested ports. Strict binding protects the launch race.

Run focused commands through the private launcher after changing into that
worktree. Use broader modes only for a stated coverage/release reason. Copy Linux
evidence into the Windows task when needed for review.

## Versioned development skills

Canonical sources live in skills/development/. The image-editing skill remains
in skills/badshop/. Review local installation changes with:

    python scripts/sync_skills.py
    python scripts/sync_skills.py --apply

The default prints differences and returns 1 when updates are available.
--apply preflights both skills and refuses to overwrite edits differing from
recorded installation hashes. For existing personal copies, --adopt records their
hashes once without changing content; review the diff before applying.
Use --destination for another installation. The .badshop-skills.json manifest
belongs in that destination, not in repository history.

## CI selection

change-scope.yml uses scripts/ci_scope.py: Markdown docs and skill text skip app jobs,
test-only changes select the affected layer, and unknown/shared inputs select broad
coverage. Manual dispatch requests all core and desktop checks. Pushing a `v*`
tag starts the installer build and smoke-test matrix, which covers the packaged
WebKit renderer. `core-result` and `desktop-result` report the selected checks
and intentional skips.

## Preventing code bloat

Before adding code, name the current owner and callers of the behavior. Reuse the
engine's pixel operations, the tool registry's schemas, and session execution for
application tool calls. Providers adapt protocols; React renders core state and
owns presentation interactions, not another domain model. The standalone parity
CLI deliberately calls the runner with FileStore. Shared validation/error helpers
remain available to approvals and RPC. Import Linter checks engine/tool boundaries
and direct provider execution dependencies; Ruff TID251 prevents direct runner
execution outside session and the standalone CLI. These static checks cannot prove
that arbitrary UI logic or dynamic imports respect the architecture; review still must.

New abstractions need current callers or a concrete boundary. Replacements remove
obsolete paths, dependencies, flags and redundant tests in the same change.
Compatibility code identifies the supported version/project format and its removal
condition. No hard file-size or line-count cap: splitting or compressing code without
reducing responsibilities is not improvement.

Install the development-only analyzers (they are not runtime dependencies):

```sh
uv sync --project core --locked --group quality
pnpm --dir app install --frozen-lockfile
```

Run relevant checks from the repository root:

```sh
# Architecture contracts; Windows PowerShell: $env:PYTHONPATH = 'core/src'
PYTHONPATH=core/src uv run --project core --no-sync lint-imports --no-cache
uv run --project core --no-sync ruff check --config core/pyproject.toml core/src
uv run --project core --no-sync vulture core/src --min-confidence 100
pnpm --dir app check:unused:strict

# Advisory candidates: nonzero means findings; investigate before deleting.
pnpm --dir app check:unused
uv run --project core --no-sync vulture core/src --min-confidence 60

# Compare the working tree to its merge-base, including new untracked source.
uv run --project core --no-sync python scripts/maintenance_report.py --base origin/main
# Test changes to these guards/report, without starting the application.
uv run --project core --no-sync python scripts/maintenance_tests.py
```

The maintenance workflow runs on PRs and main pushes. It blocks on import contracts,
Ruff, high-confidence Vulture findings, and Knip's unused files/dependencies or broken
imports. Export/type candidates and lower-confidence Python findings remain advisory
in the job summary and retained artifacts. A tool failure is not a clean result.
Knip recognizes Vite, Vitest and Playwright entry points. Its only dependency exception,
`tailwindcss`, is imported by `app/src/style.css`, which Knip does not resolve here.
Do not mark every source file as an entry point or blanket-ignore dynamic registries.
For Python, Pydantic fields, registered handlers, callbacks, and platform-specific
entry points need caller/registration review before removal. No blanket whitelist is
used; add narrow, explained exceptions only for demonstrated false positives.

Growth uses the PR merge-base as its existing-code baseline, so old large files do
not fail a new change. It reports physical production lines (including CSS), direct
runtime/development dependency changes, and per-function Lizard cyclomatic complexity
increases for Python, TypeScript/TSX and Rust. Same-name functions in one file use the
maximum complexity; renamed functions can appear new. This is a review aid, not a
semantic proof, size budget or request to refactor unrelated code. Local reports include
untracked source; CI reports committed HEAD. Review generated reports rather than
committing a second inventory of source symbols. The first baseline is the existing
code at the merge-base; no existing candidate is silently suppressed.

Use the questions in [diff-review.md](diff-review.md): what can this delete, is there
another source of truth, and does each abstraction remove actual duplication or isolate
a real boundary? Dependencies need an actual use and should be removed with that use.
