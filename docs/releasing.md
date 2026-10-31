# Building and releasing badshop

## Supported targets

Linux x86-64 (.deb, AppImage, Flatpak), Windows x86-64 (NSIS), and macOS 14+ arm64 (.dmg).
The current ONNX Runtime/rembg dependency set does not ship Intel macOS wheels, so v1
uses per-architecture Apple Silicon builds with macOS 14 or newer. Intel macOS is not silently advertised as
supported. The retired macos-13 CI runner from the initial spec is replaced with macos-15.

## Local development

Install Python 3.12, uv, Node 22, pnpm 10, Rust stable and Tauri's native prerequisites.
On Linux the build needs GTK 3, WebKitGTK 4.1, OpenSSL, a C toolchain and the app indicator
library. Development startup is `pnpm --dir app tauri dev`; Rust starts `uv run --project
core badshop-core serve` and holds its stdin pipe open. Set BADSHOP_UV to an absolute uv
path if a GUI launcher has a minimal PATH.

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

Use `badshop-core.exe` in the smoke command on Windows. The frozen smoke starts a fresh
private session, runs a Haar face detector in the spawned worker, saves and shuts down by
closing stdin, then repeats with forced core termination and verifies no worker survives. The onedir is bundled as resources, not a single-file sidecar.

The initial Linux .deb is about 370 MiB, AppImage 395 MiB and Flatpak 220 MiB. The unpacked core is
approximately 800 MB: rembg also depends
on NumPy/SciPy, numba/llvmlite and native runtimes, and LiteLLM includes provider adapters.
Installer compression reduces the download; model files add separate optional storage.

## Flatpak

`packaging/build_flatpak.py path/to/badshop.deb` (dpkg-deb or ar + bsdtar) uses the same verified Linux build,
extracts its resource layout and feeds `packaging/flatpak.json` to flatpak-builder.
Install org.gnome.Platform and org.gnome.Sdk branch 49 in the user Flatpak installation.
This v1 binary bundle avoids a second cargo/node dependency resolution; the upstream
Linux build uses committed pnpm/Cargo/uv lockfiles. A future Flathub submission can replace
the prebuilt module with generated source manifests. The home permission enables local
projects/images; network supports providers and sources; Secret Service access supports keys.
Sandboxed subscription CLIs must be available inside the sandbox; use an API/local server
profile if a host CLI is unavailable there.

## Release workflow

`native-desktop.yml` is shared by PR CI and `release.yml`: it builds and tests each
supported installer before uploading it. On a `v*` tag, `release.yml` creates a draft GitHub release. A manual dispatch builds artifacts without publishing.
The PyPI job runs only on version tags after all bundle jobs pass, through the protected
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

The required screenshot catches an empty WebView; the established loopback connection
proves the renderer executed and authenticated to its bundled core. Screenshots are
uploaded as `desktop-evidence-*`. These checks do **not** claim native file-dialog,
clipboard image, or every editing-flow coverage: browser end-to-end tests cover editing,
while native dialogs and clipboard should also receive an interactive release check.
No test driver or automation endpoint is added to the shipped application.
