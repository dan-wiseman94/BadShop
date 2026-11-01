# Desktop verification — 2026-10-31

This record covers **PR 4 at `22fa6e0` plus the scoped audit fixes described below**.
PR 4 was merged as `2d92fac` during the audit; its tree matches `22fa6e0`.
The corrections are carried in a separate follow-up PR.
It excludes the concurrent Studio, asset-library, source-card and branching work from
another checkout/thread. The checks support the workflows they exercise; they do not
establish that every provider, operating system and failure combination works.

Two different states were tested:

- **PR 4 baseline:** fresh source checks and the successful cross-platform installer
  CI run at `22fa6e0`. The native package hashes below identify this baseline.
- **Audit source:** an isolated worktree based on `22fa6e0`, with reconnect/recovery
  corrections, Gemini CLI settings and font-schema corrections, and their regressions. Source checks
  on this worktree do **not** prove the older installers contain these corrections.

The [design specification](superpowers/specs/2026-09-26-badshop-app-design.md),
implementation rulings, source and actual test assertions were reviewed alongside
the fresh runs. Browser tests spawn the real Python core in private directories;
scripted agent responses drive the real registry and image engine. No production
mock state or shipped automation endpoint was added.

## Check results

| Check | PR 4 baseline | Audit source |
|---|---|---|
| Frontend unit tests | 48 passed, 11 files | **52 passed, 11 files** |
| Strict TypeScript and Vite production build | Passed | **Passed** |
| Real-core browser workflows | 21 passed | **28 permanent tests plus 2 viewer probes passed**, 30 total in 1.2 minutes on final source; 7 other audit probes passed earlier |
| Full Python suite | 1,504 passed, 5 skipped, 1 deselected | **1,507 passed, 4 skipped, 1 deselected** in 281.91 seconds, including real Gemini settings/policy checks; separate 61-second MCP contract passed |
| Rust tests and formatting | 3 tests passed; formatting passed | No Rust production changes in this audit |
| Focused worker/disconnect/recovery tests | 3 passed | Supplemented by the real-process browser recovery cases below |
| Packaged Linux/Windows/macOS CI | Passed | Follow-up PR runs the same matrix; source results alone do not replace installer evidence |

The browser audit used a dedicated server on port 1422 with server reuse disabled.
One test-harness correction makes the production-CSP test grant Chromium local-network
permission to the configured base URL, rather than assuming port 1420. The packaged
CSP was unchanged.

The extra probes were temporary audit code, archived outside the repository.
The six permanent recovery workflows are in
[desktop-reconnect.spec.ts](../app/e2e/desktop-reconnect.spec.ts); minimum-size picking
is covered in [desktop-workflows.spec.ts](../app/e2e/desktop-workflows.spec.ts).
The ordinary browser suite therefore contains 28 tests. Generated screenshot changes were restored, the
temporary audit configuration/probes were removed, and `git diff --check` passed.
Vite's existing large-chunk advisory remains; the production build succeeded.
Ruff and whitespace checks passed. The four full-suite skips were opt-in live
provider checks, the separately run slow MCP contract and Windows-only containment;
the deselected test is the separately exercised live network source.

## Defects found and corrected

- **Temporary disconnect lost drafts.** The disconnected screen unmounted the
  composer and parameter forms. The workbench now stays mounted, hidden while
  disconnected and inert until ready, preserving local drafts and viewer state.
- **Restart recovery published an empty document too early.** The new core's startup
  snapshot cleared attachments before restore completed. Recovery now finishes before
  ready/query publication. Automatic recovery of the same document retains unsent
  text, parameter edits and valid references; older recovery snapshots prune missing
  selections and attachments. Explicit New/Open/Restore keeps its intentional reset.
- **No autosave silently discarded work.** An otherwise pristine document now keeps
  its typed-only draft across restart. If cached persisted content has no recovery
  file, the app retains it, reports the failure and stays nonready through retries.
- **Recovery allowed stale user actions.** Mutations and user-facing document
  snapshots now require ready state. Bootstrap uses direct RPC. Offline close Cancel
  preserves the cached document; only explicit Discard permits closing without Save.
- **Two tool forms shared control IDs.** Opening the palette while a timeline form
  was present duplicated IDs such as `root_image`, so a palette label targeted the
  timeline input. Each form now has a stable unique ID prefix. The regression checks
  label ownership, stable IDs after typing and independent form submissions.
- **Coordinate instructions pushed the image outside the minimum-size viewer.** The
  sticky hint occupied space beside the image in the same flex row. It now occupies
  its own wrapping row below the scroll stage. A real 900×600 browser regression
  requires the whole fitted image to stay inside the viewer and checks drag results
  against source-image coordinates. The actual detected-face overlay probe also passed.
- **Modern Gemini CLI hook settings were schema-invalid.** The adapter correction
  uses the installed CLI's `hooksConfig.enabled` boolean instead of treating `hooks`
  as that setting. Passing schema checks does not establish a successful live turn.
- **Large font libraries overwhelmed every model request.** Enumerating the local
  font catalogue added roughly 100 KB to the text-tool schema. Small catalogues still
  use explicit enums; larger ones use bounded filename examples. Runtime validation
  still accepts all discovered names and rejects model-supplied paths or unknown names.
  The same Ollama request shrank from 43,709 to 11,127 tokens. An actual 4,096-token
  server still rejects that request; the README now documents context configuration
  and the generic rejection message mentions the configured context limit.
- **A process-cleanup assertion raced kernel status publication.** Stress testing
  found descendants already killed but still reported running for at most 2.3 ms.
  The assertion now polls for disappearance/zombie status for at most one second;
  suppressing SIGKILL makes the negative-control test fail. Production cleanup did
  not need changing.

The reconnect, early-publication and no-autosave failures were reproduced before
their fixes. Permanent tests kill owned core processes, change endpoints, hold the
actual restore reply, and cover successful, damaged, older and absent autosaves.
Independent review found no blocking issue in the scoped recovery changes.

## Real providers and complete editing

Fresh opt-in calls exercised actual Claude and Codex CLI image delivery and resumed
conversation, Gemini API vision/native tools and JSON fallback, and local
`qwen3-vl:2b` through Ollama native tools, JSON fallback and its OpenAI-compatible
endpoint. Each individual image/tool smoke passed. These are representative calls,
not evidence that every model can carry out the complete composition.

A real Claude session completed the supplied-portrait workflow through the normal
CoreApp, worker and MCP approval boundary: two face inspections, cutout, paste,
laser eyes, seeded deepfry and export. Five mutations waited for explicit approvals.
The harness exported the result, saved a `.badshop` project, created another session,
reopened the saved project and replayed without cache. Every step's output IDs were
identical. The final output SHA-256 was
`68edd0b8d4fab0eb4e96d3f63bb1dc550b674b00c8ae2ef0eb923a51a06bfa72`.

Modern Gemini CLI configuration was loaded with the real installed 0.66 settings
loader and its policy engine. After fixing its settings, a live CLI run still failed
with upstream 503/daily-quota errors. A subsequent full Gemini API editing attempt
also reported rate limit/quota. Neither full workflow is counted as passed, and no
further quota retries were made. Earlier small Gemini API smoke successes do not
establish full editing success.

With the font fix and a 32,768-token private Ollama server, the full portrait request
was accepted but exceeded the application's 120-second completion deadline. A simpler
single-edit request also timed out on this CPU setup. Both ended with visible timeout
errors and closed requests; neither produced a completed edit. Native/JSON/compatible
one-tool vision smokes passed earlier, but complete local-agent editing remains
unconfirmed on this machine. No app timeout was extended to manufacture a pass.

The 61-second MCP approval heartbeat contract also passed in a separate opt-in run.
The tool stayed pending until the simulated user's decision; this exercises the real
SDK connection rather than a shortened timer or a mocked transport.

To reproduce the ordinary source checks from the repository root:

```sh
uv run --project core pytest core/tests -q
uv run --project core ruff check core packaging
pnpm --dir app test
pnpm --dir app build
pnpm --dir app exec playwright test
cargo test --manifest-path app/src-tauri/Cargo.toml --locked
cargo fmt --manifest-path app/src-tauri/Cargo.toml -- --check
```

The opt-in settings/policy checks require the isolated Gemini package described in
`core/tests/test_gemini_policy.py`. The slow approval contract is:

```sh
BADSHOP_LONG_MCP_TEST=1 uv run --project core pytest \
  core/tests/test_mcp_proxy.py::test_sdk_real_sixty_second_approval_heartbeat -q
```

## Workflow coverage

| Area | Evidence exercised |
|---|---|
| Setup and settings | First run/manual mode, choosing saved profiles, profile-kind changes, offline checks versus explicit connection probes, visible setup errors and download ownership/cancel state. |
| Chat and approvals | Streaming/retry atomicity, approve/edit/reject with notes, Stop, amended parameters verified in the real core, and typed drafts across reconnect/recovery. |
| Tool forms and keyboard | All 23 registry forms rendered at 900×600 without page errors or horizontal clipping; Run actions were reachable. Tab/Shift-Tab stayed inside Settings; Escape restored focus and canceled coordinate picking without losing the draft. |
| Viewer and timeline | Input-bound coordinate picking, repeatable drawing fields, before/after, 100% and Fit zoom, grid, replay, remapped references, parameter-draft conflicts, deleting the last step and older-step export. Extra probes sampled distinct visible GIF frames and verified real Haar overlay geometry at 50%, 100% and Fit, picking through it, and removal when selecting an unrelated image. |
| Projects and files | Actual imports, Save/Save As/Open, recipe export, canceled pickers, failed saves/Open, stale replacement guards, same-ID earlier-save reopen and autosave restoration. |
| Errors and recovery | Modal validation/engine errors, provider-specific Retry, readiness guards, cached work retained through damaged/missing recovery, and offline close Cancel/Discard callback coverage. |
| Engine and protocol requirements | The requirement audit inspected golden/parity, exact save/reopen/replay, approval/budget/cancellation, authentication, MCP scope, secret isolation and worker-containment assertions. Fresh core/provider results complement this source-level coverage review. |

The permanent browser workflows are in
[controller.spec.ts](../app/e2e/controller.spec.ts),
[desktop-session.spec.ts](../app/e2e/desktop-session.spec.ts),
[desktop-workflows.spec.ts](../app/e2e/desktop-workflows.spec.ts) and
[desktop-reconnect.spec.ts](../app/e2e/desktop-reconnect.spec.ts).

## Fresh frozen core

A clean PyInstaller build of the audit core passed actual keychain storage/retrieval/
deletion, authenticated RPC, spawned Haar execution, revision-guarded Save/Open,
normal EOF exit and forced-core-death worker cleanup. Its SHA-256 is
`4ca9674d0194c4070ffd33f3ca05e835044e8fbd426b9d9e73a633920094bfd4`.
The frozen MCP schema check returned all 23 tools, with 1,076 characters for the font
field and 27,536 characters across their parameter schemas on this host.

## Baseline native evidence

[Desktop CI run 41250064431](https://github.com/dan-wiseman94/BadShop/actions/runs/41250064431)
passed for PR 4 / `22fa6e0`: Linux `.deb`, AppImage and Flatpak, Windows NSIS, and
macOS arm64 DMG. These checks covered frozen resources/keychain/RPC/process handling,
visible renderer/socket activity, normal close/Quit and no live tracked descendants.
macOS logged that Quit passed through the project-close guard. A visible socket is
not itself proof of authenticated editing; separate RPC and Linux interactive checks
provide that evidence. The Flatpak screenshot caught the connecting state.

Actual Linux GTK testing under private Xvfb/DBus exercised Import, Save As and Open
pickers, native clipboard image reading, and dirty-close Cancel/Save & close/Discard.
Saved project ZIP contents were independently read and reopened; clipboard RGB bytes
exactly matched the fixture. Save wrote 250,229 bytes; Save & close updated the actual
project to 1,135,560 bytes and exited 0. A separate installed-core crash test replaced
the owned core, restored the synthetic autosave and rendered its image, then closed
through the dirty-project dialog without live children.

| Baseline artifact | SHA-256 |
|---|---|
| Bundled core executable | `0172c598c875aabdd8b4d94dbe3868e61da3ccae41f8f29f5ac55cdc35cd9c2f` |
| Linux `.deb` | `ad00f7aa9ad00605860c13ca7f3018e98e56103c39e3d14f7b9952e17ea30b9b` |
| Linux AppImage | `9604c097724971dbd0e0eaacb37109dd498cda22ad221fc83c6c9eb6148f3e4a` |
| Flatpak | `408ffd175f1027bf9b0e0709ca69d6391a73f07df52222e39a88ece57a557cc6` |

Isolated native **Wayland lifecycle passed** under private KWin: a real Wayland
surface, owned core connection and compositor-initiated close, with `DISPLAY` removed
to prevent X11 fallback. The private compositor's screenshot path failed, so this is
**not visual, GPU-rendering, clipboard or portal-picker verification**.

## Limits to retain

- Gemini CLI's corrected configuration passed schema checks, but its complete live
  reply/resume remains blocked by upstream 503/quota failures. It remains experimental;
  parser fixtures and adapter checks are not substitutes for that live result.
- Windows/macOS native file pickers, clipboard image roundtrips and dirty-dialog
  decisions were not manually exercised. Linux GTK interactions were; Wayland visuals
  and KDE portal interactions remain unverified.
- AppImage extraction launch was tested; the real FUSE mount path was not. macOS
  support follows the documented Apple Silicon scope, not an Intel/universal claim.
- Chromium is the browser-test engine. The production-CSP test supplies a test native
  bridge; the Linux native checks separately exercise actual WebKit/GTK bindings.
- Rendering all forms does not execute every tool through every widget combination.
  GIF playback and face-overlay geometry/picking were separately checked in Chromium;
  that does not establish every animation format or native renderer combination.
- Live provider samples do not cover every account/model or the complete flagship
  composite on every provider. Network-source and asset-download permutations are not
  exhaustive. BiRefNet's measured Linux peak was about 9,328 MiB with a 12,288 MiB worker
  limit; equivalent Windows/macOS memory measurements remain unverified.
- The successful old installer CI cannot be presented as installer validation of the
  newer audit-source fixes. Signing, notarization, auto-update and release publication
  retain their documented scope and maintainer requirements.

## Local run records

The detailed local reports are `/tmp/badshop-desktop-verification.md`,
`/tmp/badshop-native-verification.md` and `/tmp/badshop-requirements-audit.md`.
Final frontend logs are `/tmp/badshop-viewer-final-unit-2.log`,
`/tmp/badshop-viewer-final-build-2.log` and `/tmp/badshop-viewer-final-browser-2.log`.
The final Python log is `/tmp/badshop-core-audit-final.log`; the separately run slow
MCP contract is `/tmp/badshop-long-mcp-final.log`.
Audit screenshots are under `/tmp/badshop-desktop-probes/`; the baseline native
dialog/hash/ZIP evidence is under
`/home/dan/.cache/badshop-native-bindings/run-5f41010p/`.
These workstation paths are provenance records, not durable release downloads; the
linked CI run and tracked tests are the portable evidence.
