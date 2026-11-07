# Building and releasing badshop

## Supported targets

Windows x86-64 (NSIS setup.exe), Linux x86-64 (.deb, AppImage, Flatpak), and macOS 14+
with separate Intel x86-64 and Apple Silicon arm64 disk images. The macOS jobs use
`macos-15-intel` and `macos-15`, respectively. Each mounts and launches its built
installer and verifies the shell and bundled core's architecture.

Intel macOS resolves ONNX Runtime 1.23.2, numba 0.62.1, llvmlite 0.45.1 and NumPy 2.3
through platform markers in the shared lockfile. CI also exercises the Intel image
engine and a real U2-Net cutout in its frozen worker.

## Local development

Install Python 3.12, uv, Node 22, pnpm 10, Rust stable and Tauri's native prerequisites.
On Intel macOS, the locked cryptography dependency builds from source. Install
OpenSSL with `brew install openssl@3`, then run the following in the terminal used
for setup and packaging.

```sh
export OPENSSL_DIR="$(brew --prefix openssl@3)"
export OPENSSL_STATIC=1
export MACOSX_DEPLOYMENT_TARGET=14.0
```

On Linux the build needs GTK 3, WebKitGTK 4.1, OpenSSL, a C toolchain, the app indicator
library, and the TBB runtime (`libtbb12` on Ubuntu). TBB satisfies the bundled numba
plugin's ELF dependency; AppImage packaging checks even optional native plugins.

Development startup is `start.cmd` on Windows (see the [Windows setup guide](windows.md#run-from-source)),
`./start.sh` on Linux/macOS, or
`pnpm --dir app tauri dev --config src-tauri/tauri.source.conf.json` after dependency setup.
The source config omits frozen release resources, which are not needed for development.
Rust starts `uv run --project
core badshop-core serve` and holds its stdin pipe open. Set BADSHOP_UV to an absolute uv
path if a GUI launcher has a minimal PATH.

See [development and testing](development.md) for `./verify.sh`, private Linux desktop
tests, acceptance criteria, evidence, and worktree setup.

## Build and test

```sh
uv sync --project core --locked --group build
uv run --project core pytest core/tests -q
pnpm --dir app install --frozen-lockfile
pnpm --dir app test
pnpm --dir app build
pnpm --dir app exec playwright install chromium
pnpm --dir app exec playwright test
cargo test --manifest-path app/src-tauri/Cargo.toml --locked
uv run --project core --group build python packaging/build_core.py
uv run --project core python packaging/smoke_core.py packaging/core-dist/badshop-core/badshop-core
pnpm --dir app tauri build
```

Freezing always clears PyInstaller's analysis cache. Use `badshop-core.exe` in the smoke
command on Windows. The frozen smoke starts a fresh private session, runs a Haar face
detector in the spawned worker, verifies revision-guarded Save As/Save/Open and rejects
stale writes and replacement of an unsaved project. It shuts down by
closing stdin, then repeats with forced core termination and verifies no worker survives. The onedir is bundled as resources, not a single-file sidecar.

The initial Linux .deb is about 370 MiB, AppImage 395 MiB and Flatpak 220 MiB. The unpacked core is
approximately 800 MB: rembg also depends
on NumPy/SciPy, numba/llvmlite and native runtimes, and LiteLLM includes provider adapters.
Installer compression reduces the download; model files add separate optional storage.

## Flatpak

`packaging/build_flatpak.py path/to/badshop.deb` (dpkg-deb or ar + bsdtar) uses the same verified Linux build,
extracts its resource layout and feeds `packaging/flatpak.json` to flatpak-builder >= 1.3.4.
This version minimum uses `appstreamcli compose` for metadata; SDK 49 no longer supplies
the legacy `appstream-compose` executable. On Ubuntu 22.04, CI installs the current
builder and AppStream compose support from the [official Flatpak stable PPA](https://github.com/flatpak/ppa-flatpak)
after building and testing the .deb and AppImage, preserving their Ubuntu 22.04 baseline.
Install org.gnome.Platform and org.gnome.Sdk branch 49 in the user Flatpak installation.
This v1 binary bundle avoids a second cargo/node dependency resolution; the upstream
Linux build uses committed pnpm/Cargo/uv lockfiles. A future Flathub submission can replace
the prebuilt module with generated source manifests. The home permission enables local
projects/images; network supports providers and sources; Secret Service access supports keys.
Sandboxed subscription CLIs must be available inside the sandbox; use an API/local server
profile if a host CLI is unavailable there.

## Release workflow

### In-app updates

Settings → Updates provides manual checks and a persisted automatic-check toggle
(on by default, checks five seconds after launch and every six hours). Downloads
are verified before the existing save/discard/cancel dialog. Installation is explicit
and restarts the app. Windows NSIS, macOS apps and Linux AppImages support this;
Debian and Flatpak users update through their package manager or a new download.
Development builds do not self-update.

Before tagging the first updater-enabled release, generate a durable signing key
with `pnpm --dir app tauri signer generate -w <private-key-path>` outside the checkout.
Keep a secure backup. Set repository variable `BADSHOP_UPDATER_PUBLIC_KEY` to the
public key file contents and repository secret `TAURI_SIGNING_PRIVATE_KEY` to the
private key contents; set `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` if encrypted.
These are updater signatures, separate from OS code signing. Never commit the private key.
The public key is embedded at compile time; unsigned development/local builds report
that updates are unavailable. Tag builds fail when signing configuration is absent.

The native release matrix produces signed updater artifacts as well as installers.
`packaging/update_manifest.py` requires all four artifacts and signatures and generates
`latest.json`. Publish that file with the artifacts by publishing the draft release.
The stable feed uses GitHub's `/releases/latest/download/latest.json`, so drafts and
prereleases are not offered automatically. Existing versions without this feature
need one manual installation. Keep the signing key stable across subsequent releases.

Before publishing, test a version-to-version signed installation on Windows, each
Mac architecture and AppImage: verify version after restart, saved project bytes,
signature rejection, download failure/retry and no surviving old core processes.
Component tests mock the native boundary and do not substitute for this release check.

Pushing a `v*` tag starts `release.yml`, which calls `native-desktop.yml` to build
and test each supported installer before attaching it to a draft GitHub release.
Both publishing jobs require the core and frontend checks and the native bundle matrix
to pass on the tagged revision. The PyPI job uses the protected
`pypi` GitHub environment and trusted publishing. Configure the repository/environment as
a trusted PyPI publisher before its first release. Match the tag to Python, frontend and
Tauri package versions before tagging. Release tags and external publication are explicit
maintainer actions, not part of ordinary development.

Unsigned v1 installers: on macOS, use System Settings → Privacy & Security → Open Anyway
if Gatekeeper blocks the downloaded app; on Windows, SmartScreen may require More info →
Run anyway. Only bypass these prompts for builds whose source and release you trust.

## Release checks needing actual environments

Run the opt-in `test_live_provider.py` smoke against the intended provider and model; cloud
calls require an explicit environment opt-in. Authenticate each supported subscription CLI
outside badshop and test a real image/approval turn.

The required frozen-core keychain smoke stores a unique synthetic credential, retrieves it
inside the frozen executable to authenticate to a loopback-only endpoint, then deletes it
and verifies absence. Linux CI supplies a private D-Bus Secret Service; Windows and macOS
use their real OS credential stores. No cloud account or provider quota is involved.

Run `packaging/measure_model.py --model birefnet-general` for worker memory needs on release
hardware. The installed-desktop job additionally launches each platform's packaged GUI; passing
core tests alone does not satisfy that job. Missing GUI or keychain access fails rather
than silently skipping a platform.

The reference engine and skill remain unchanged as parity fixtures. Installed users can
call `badshop` after `uv tool install ./core` (or the published PyPI package after release).


## Initial model memory measurement

On Linux x86-64, BiRefNet-general on a 761×1000 image peaked at **9,328 MiB RSS** and
completed with a 12,288 MiB worker limit. An 8,192 MiB limit stopped the worker. The default
3,072 MiB limit remains appropriate for lighter tools; the model picker explains the larger
limit. Reproduce with:

```sh
uv run --project core python packaging/measure_model.py --memory-mb 12288
```

Repeat this on Windows and macOS before their release. The downloaded model is cached;
model measurement is separate from the lightweight installer smoke test.


## Live validation performed during implementation

- Gemini `gemini-3.8-flash`: vision plus native tool calling and forced JSON fallback passed.
  The first fallback request exceeded 90 seconds; a retry with a 180-second harness limit
  completed in 76 seconds. Gemini 2.5 Flash was
  unavailable to this account; the adapter now explains unavailable model/endpoint errors.
- Local Ollama `qwen3-vl:2b`: vision plus native tools and forced JSON fallback both passed.
- Claude Code and Codex: initial turn plus resumed image inspection via the actual MCP proxy passed.
- Modern Gemini CLI 0.66.0: isolated policy-engine check confirms badshop tools allowed and
  built-in/other-server tools denied; the preinstalled 0.1.13 is correctly rejected. A real
  model invoked MCP `view` and consumed the image. Full reply/resume remains unverified:
  the final bounded probe received upstream HTTP 503 high-demand errors and exhausted
  240 seconds of retries. Gemini CLI remains experimental.
- Linux .deb and Flatpak: visible native UI, renderer/core connection and clean window-close
  shutdown passed under isolated Xvfb. AppImage also passed via its extraction runner (FUSE mount not exercised); native runtime
  smoke is separately tracked from the browser editing tests.

The live harness creates synthetic image inputs and temporary sessions. Cloud smoke may use
account quota; it runs only when its environment flags are set. These checks establish the
selected model/CLI behavior, not compatibility with every upstream version or account.


To repeat native Linux lifecycle checks on an isolated display:

```sh
xvfb-run -a --server-args="-screen 0 1600x1100x24" uv run --project core python packaging/smoke_desktop.py -- /path/to/badshop-desktop
```

This needs Xvfb, xdotool and ImageMagick. The script requires a visible application
window, a renderer connection to the bundled core, a nonblank screenshot of the content,
window-manager close, and process cleanup. `--screenshot PATH` retains the screenshot. Use the extracted .deb binary, or pass an AppImage followed by
`--appimage-extract-and-run`. Run it on its own display, not the active desktop.


## Native installer checks

`packaging/smoke_installer.py --screenshot packaging/native-smoke.png` discovers the one
installer for the current OS. It extracts the .deb payload without root, silently installs
the Windows NSIS package into a temporary directory, or mounts the macOS DMG and copies
its .app out before launching. Windows sends the normal `WM_CLOSE` request; macOS uses
`NSRunningApplication.terminate()` (normal application quit). Both require exit status 0
and no surviving core/WebView children. macOS's harness uses PyObjC Cocoa/Quartz and an
actual logged-in graphical session; CI installs these harness dependencies separately.
Linux runs on Xvfb; AppImage's extraction runner and the installed Flatpak receive the
same lifecycle check. AppImage FUSE mounting is not covered.

The required screenshot catches an empty WebView. The established loopback connection
confirms the renderer opened a socket to its bundled core. The Windows installer check also
imports an image using the native picker, applies Deepfry, cancels a dirty-window close, then
saves and closes through the native dialog. It relaunches the app, opens the project through
the native picker, and compares the rendered output with the saved artifact hash.
The Windows test uses a private WebView2 profile and a temporary debugger endpoint. On elevated
GitHub Actions runners, it restores the two app-specific machine policy values after each launch.
Run it locally on an isolated Windows runner with an interactive desktop and a non-elevated shell.
Its screenshots, app logs, WebView traces, and
`summary.json` are uploaded as `desktop-evidence-*` alongside the other platforms' screenshots.

```powershell
uv run --project core --with playwright==1.58.0 --with pywinauto==0.6.9 python packaging/smoke_installer.py --screenshot artifacts/verification/installed-windows/native-smoke.png
```

Clipboard input and the macOS/Linux native file dialogs still need interactive release checks.
