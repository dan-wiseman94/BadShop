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
uv run --project core --group build python packaging/release_inventory.py --label linux-x64
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

### Nightly builds

`nightly.yml` builds main daily at 08:23 UTC (02:23 Central standard time,
03:23 Central daylight time), or through **Actions → nightly → Run workflow**
with main selected. The schedule becomes active when the workflow lands on main;
GitHub may delay scheduled runs. Forks and dispatches from other branches skip it.

Each successful run stages a separate `nightly-YYYYMMDD-RUN_ID-ATTEMPT`
draft GitHub prerelease containing Linux AppImage/deb/Flatpak, Windows x64 NSIS,
and macOS arm64/x64 DMGs, plus SBOMs, SHA256SUMS and build attestations.
The release links the exact source commit and verification run. Core, frontend,
locked-dependency security and the existing installed-desktop matrix must all pass.
The draft remains private until the same candidate acceptance and protected promotion
used for stable releases passes. A successful scheduled build alone never publishes.
Reruns use a new tag, so published bytes are never overwritten. Prior nightlies
remain available; no release/tag deletion is automated. CI evidence follows the
existing artifact retention policy (failed installer artifacts: three days).

Download from [all releases](https://github.com/dan-wiseman94/BadShop/releases),
or select **Settings → Updates → Update track → Nightly** in an updater-enabled
build. Stable is the default; the choice persists across restarts. A track change
clears the previous offer and applies to both manual and automatic checks. Switching
is disabled while checking, downloading or installing. Local only still blocks
network access; installation still requires an explicit click and the existing
save/discard/cancel flow after signature verification.

Nightly builds use the same durable updater signing key as stable releases and
require the same repository signing configuration. Desktop bundle versions are
`BASE-nightly.RUN_ID`; Python/Cargo source package versions retain the base version.
The native build stamps Tauri configuration after validating the source versions.
The unique prerelease includes its signed `latest.json`; only after acceptance and
publication does the promotion workflow update the mutable `nightly` prerelease's `latest.json`
pointer. That pointer references immutable dated downloads. The release body retains
the promoted version even if replacing the feed file fails. Older run IDs cannot
replace it; the same run may repair a missing feed file. A promotion failure
leaves the dated downloads available and fails the job; rerun to retry promotion.

Nightlies never become GitHub's latest stable release and never publish to PyPI.
Stable users only see stable updates; Nightly users only see newer nightly builds.
Switching tracks offers that track's latest build even when its version is lower,
so returning to Stable does not require waiting for stable to catch up. Back up
projects before testing or downgrading. Both tracks share the app identity and
settings; there is no side-by-side install. Debian and Flatpak still require manual
or package-manager installation. OS signing/notarization remains separate from
updater signatures and is not provided by this workflow.

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
`latest.json`. Publish the complete draft through the protected promotion workflow below.
The stable feed uses GitHub's `/releases/latest/download/latest.json`, so drafts and
prereleases are not offered automatically. Existing versions without this feature
need one manual installation. Keep the signing key stable across subsequent releases.

Before publishing, test a version-to-version signed installation on Windows, each
Mac architecture and AppImage: verify version after restart, saved project bytes,
signature rejection, download failure/retry and no surviving old core processes.
Component tests mock the native boundary and do not substitute for this release check.

macOS packaging must select both `app,dmg`: the DMG alone does not produce the
updater archive. The matrix rejects a missing or ambiguous `.app.tar.gz` before
uploading its release artifacts. To recover packaging for an existing release tag
without moving the tag, manually run `native-desktop.yml` with `source_ref` set to
the full `refs/tags/vX.Y.Z`. This checks out that exact source and reruns the native
matrix with the current packaging workflow. Only use its artifacts after every
selected installer check passes; generate the feed from that run's complete set.

Pushing a `v*` tag starts `release.yml`, which calls `native-desktop.yml` to build
and test each supported installer before attaching it to a draft GitHub release.
The tag must already belong to main before builds start. Draft creation requires core,
frontend, security and the native bundle matrix to pass on that revision. Public promotion
additionally requires successful main runs of core, desktop, maintenance and security for
that exact SHA, covering maintenance and selected Rust unit/format checks.
The PyPI job runs only after successful stable promotion, uses the protected
`pypi` GitHub environment and trusted publishing, and is disabled unless the repository
variable `BADSHOP_PYPI_PUBLISH` is `true`. Current releases are desktop downloads only.
Configure PyPI's trusted publisher with workflow `promote-release.yml` and environment
`pypi` before enabling it. A draft never triggers Python publication.
Match the tag to Python, frontend and
Tauri package versions before tagging. Release tags and external publication are explicit
maintainer actions, not part of ordinary development.

Current free releases disclose Windows publisher and Apple notarization warnings; OS signing
remains a later milestone under the v1 design scope. Use platform signing and verify a clean
download on a fresh machine before claiming a trusted first-install experience.
Updater signatures do not replace Authenticode or Apple notarization.

### Publication and integrity gates

The exact Python lock (all groups), JavaScript lock (including development tools), and
Rust lock are audited by `security.yml` on pull requests, main, weekly, and release calls.
Any known vulnerability blocks; Rust warning exceptions are exact package/version/advisory
reviews in `packaging/rust-advisory-review.json`, expire on 2026-12-07, and require fresh
call-site/upstream review before renewal. Passing with a reviewed warning is not a clean
dependency bill of health. External Actions are pinned to immutable commits.

Native packaging collects actual license notices, inventory coverage, and a CycloneDX 1.6
SBOM under `core-dist/badshop-core/legal/`. `release_inventory.py` fails on missing notice
files. Each platform also uploads `badshop-<label>.licenses.json`, copied from its actual
coverage report. Pending manual reviews may remain in a private draft so its real contents
can be inspected; promotion requires an explicit recorded approval and evidence for every
listed package on every platform. No existing reviews are automatically marked resolved.
Cargo MPL-covered source is copied into `legal/covered-source/`.
The SBOM deliberately includes build/non-host dependencies and is not a precise binary
reachability claim. Use the platform sidecar SBOM, notices, model/font licenses and an
inspection of the final installer together.

The release publisher generates `SHA256SUMS` for every asset, rejects duplicate uploaded
basenames, and creates GitHub build-provenance attestations. These are implemented workflow
steps; a local source run does not prove a published attestation. Verify the downloaded
bytes against the checksums and use `gh attestation verify <asset> --repo dan-wiseman94/BadShop`
for provenance after the release workflow has actually run.

Optional PyPI publication waits for successful stable promotion and separate environment
approval. If a required gate fails, retain the draft and failed-run evidence. Never
overwrite an already published version with different bytes.

### Accept and promote an exact candidate

Stable and nightly publication share `packaging/release_gate.py` and
`.github/workflows/promote-release.yml`. Build jobs record `release-candidate.json`
with the source SHA, build run/attempt, version and tag, then hash and attest the complete
asset set. Candidate metadata, license reports and SBOMs are included in those checksums.

1. Download the complete private draft into an empty directory:

       gh release download vX.Y.Z --repo dan-wiseman94/BadShop --dir artifacts/verification/candidate

2. Generate a pending acceptance record:

       python packaging/release_gate.py template artifacts/verification/candidate vX.Y.Z --output packaging/release-acceptance/vX.Y.Z.json

   Use the immutable nightly tag in both positions for a nightly candidate.
3. Perform the platform checks below. Fill every generated entry with the actual result
   and a retained HTTPS evidence link, and set `reviewed_by` to the maintainer's GitHub
   login. Platform results must be `passed`; license resolutions must be `approved`.
   `os_trust` also accepts `unsigned-disclosed`, with evidence of the v1 unsigned warning
   and release disclosure. That exception never waives updater signature tests.
4. Validate the completed record:

       python packaging/release_gate.py check artifacts/verification/candidate vX.Y.Z --acceptance packaging/release-acceptance/vX.Y.Z.json

   Commit it through a PR to main. The record includes the source SHA and the SHA-256
   of SHA256SUMS; a rebuild, changed inventory or changed download requires fresh review.
   The template command refuses to overwrite an existing record.
5. Dispatch **Actions → promote release** from **main**, supplying the tag. Review the
   committed record and approve the release environment deployment. The workflow
   downloads the draft again, checks every byte, the current asset digests, all required
   main workflows, the successful build attempt, tag/source identity and GitHub provenance
   of SHA256SUMS, restricted to the expected builder and source SHA. Only then does it
   make the draft public. Missing, failed, skipped or stale evidence fails closed.

The six acceptance targets are Windows x64, both Mac architectures, AppImage, deb and
Flatpak. The template enumerates their required checks and each platform inventory's
pending license decisions. Evidence links must refer to retained results, not a promise
to test later. The gate validates completeness and identity; the maintainer must assess
the truth and adequacy of manual evidence. Signing keys and legal approvals are never
fabricated by the gate.

Promotion is serialized. A retry revalidates the same evidence and published bytes without
replacing them, allowing a failed nightly-feed update to recover. Older nightlies cannot
move the feed backwards. PyPI retries remain subject to its own approval and version
immutability. Historical drafts lacking candidate metadata must be rebuilt through this
workflow; there is no legacy evidence bypass.

Repository settings are part of enforcement:

- The release and pypi environments require dan-wiseman94 approval, disallow administrator
  bypass and allow deployments from the main branch only. Self-review remains allowed
  because this is a single-maintainer repository; this is deliberate publication consent,
  not a claim of independent human review.
- An active tag ruleset prevents updates and deletion of v* and nightly-* tags with
  no bypass actors. The mutable nightly feed is excluded.
- Main retains required maintenance, core-result, desktop-result and audit checks.

Environment rules apply to Actions jobs, not GitHub's manual Release UI. Repository
administrators can change protections or publish manually; maintainers must use this
promotion path. These gates prevent accidental workflow bypass and reject incomplete
evidence, but cannot constrain an administrator who deliberately changes repository policy.

### Signing and acceptance handoff

The maintainer must provision the signing identities and repository secrets; none are
generated, purchased or replaced by an ordinary source task. Follow the current official
[Windows signing guide](https://v2.tauri.app/distribute/sign/windows/) for the chosen
certificate/key service and [macOS signing guide](https://v2.tauri.app/distribute/sign/macos/)
for Developer ID and notarization. Record the signing identity, certificate expiry,
timestamp/notarization result and recovery owner without storing secrets in the evidence.

For **each exact candidate** retain:

| Target | Required evidence before promotion |
| --- | --- |
| Windows x64 | Downloaded NSIS trust check (record unsigned v1 disclosure when applicable); install/uninstall; native import/save/open; image clipboard paste into a real target app; keychain cleanup; signed upgrade and rejection of a tampered update |
| macOS arm64 and x64 | Downloaded DMG and app archive; trust/notarization result (record unsigned v1 disclosure when applicable); fresh launch; native file/clipboard workflows; keychain; signed upgrade and tamper rejection on each architecture |
| Linux AppImage | Downloaded runtime on a supported distribution; clipboard into a target app; signed upgrade, interruption/retry, old-core cleanup and project recovery |
| Linux deb/Flatpak | Install/run/uninstall using the package manager; file access and credential service; document reopen; explicit package-manager update path |

For upgrades, create/save a project first, interrupt the download, retry, reject a changed
signature, complete an authentic upgrade, compare saved artifact bytes, and verify the
old core/worker is gone. Repeat rollback using a backup; older versions must not overwrite
newer project formats. Browser mocks and a private Linux debug build are not these results.

Flatpak still requests home/network access: the Python core owns user-chosen project/image
paths and provider/source traffic, and host CLIs are not automatically available inside
the sandbox. Portal-only grants across the Rust/Python boundary require a separate tested
file-access change. This package must not be marketed as a restrictive filesystem sandbox.

## Release checks needing actual environments

The **candidate acceptance** workflow downloads an existing candidate without
rebuilding it. Its disposable Windows, Mac and Linux runners retain installed
license/source inspections, native file and Chromium clipboard-paste evidence,
package-manager lifecycle checks, and updater interruption/tamper/retry/rollback
results under `candidate-acceptance-*`. The public v0.4.3 installers are the
upgrade baseline. The updater fault server stays on loopback; only these disposable
runners temporarily trust its certificate. Application signatures and updater
verification remain enabled. The script refuses ordinary developer workstations.

Dispatch with `candidate_tag`; inspect the retained results before filling the
acceptance record. A successful workflow is evidence for the named checks, not an
automatic legal approval or permission to skip the protected promotion workflow.

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


## Historical live validation before release-readiness remediation

The following evidence predates the release-readiness changes. It describes earlier tested
builds, not a pass for the current candidate. Repeat the applicable checks on the exact release
revision; see [the remediation report](release-implementation.md) for fresh results and gaps.

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
