# Desktop App and Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Implement the remaining v1 desktop, provider, MCP and release work in the approved design.

**Architecture:** Keep Python as the sole session/tool authority. A Tauri 2 shell owns the core process and React renders the JSON-RPC API. Subscription CLIs execute their own loops through a stateless MCP proxy into the same approval gate.

**Tech Stack:** Python 3.12/uv, LiteLLM, MCP SDK, React 19/TypeScript/Vite/pnpm, Tauri 2/Rust, PyInstaller, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-26-badshop-app-design.md`; inherited requirements: `2026-09-27-plan-1-carry-forward.md`.

## Global Constraints

- No image-generation model ever touches pixels. Preserve the reference engine's pixel logic.
- Python core + Tauri shell; no hosted web product. One session/window in v1.
- Every tool call passes through session execution and its existing approval policy.
- Artifacts and session files never store credentials; plaintext credentials require explicit consent.
- CLI provider permissions apply only to badshop MCP; do not enable global approval bypass.
- Cross-platform unsigned installers. Publishing/version tags are release actions, not automatic development side effects.

## Review Focus

- Stop/exit during model, worker, MCP approval or core startup leaves no orphan work.
- A core restart replaces credentials and stale UI requests without losing autosaved work.
- Reopening a project refreshes images, forms and provider selection without leaking old state.
- Unknown/malformed CLI events and disconnected peers fail visibly without corrupting the session.
- Frozen worker startup and optional assets work from an installed resource directory.

### Task 1: Complete core provider and operational features

**Files:** `providers/litellm_provider.py`, new `diagnostics.py`, `engine/assets.py`, corresponding new tests.
**Interfaces:** Preserve Provider.complete/Reply. Add safe JSON-mode tool fallback; logging setup and diagnostic report helpers; cancellable/resumable downloads through existing asset callback interface. Do not edit server integration files; give root exact integration APIs.
- [x] Test unsupported native tools, malformed fallback JSON, cancellations, resume/range/checksum behavior and credential redaction.
- [x] Implement fallback with image context and existing validation/approval execution; explicit warning surfaced to callers.
- [x] Implement rotating logs, diagnostic report and asset resume/cancel; preserve existing downloader tests.
- [x] Run focused Python tests and report integration requirements.

### Task 2: Desktop frontend

**Files:** `app/package.json`, `app/src/**`, Vite/TS/Vitest/Playwright config, frontend tests; excludes `app/src-tauri/**`.
**Interfaces:** Existing CoreApp methods/events are authoritative. Tauri `core_connection` returns `{port,token,log_path}`; `core-status` events announce `{state,port?,token?,log_path?,attempt?}`; commands `core_restart`, `diagnostics` (text). Native dialogs/clipboard/opener use official Tauri plugins. Development-only connection override supports browser E2E against a real core.
- [x] Build typed authenticated RPC client with cancellation/disconnect errors and query invalidation; tests cover reconnect and pending calls.
- [x] Implement three resizable panes: streamed Markdown chat/approvals, pixel viewer with grid/face boxes/before-after/pick coordinates, timeline/forms/edit/replay/delete and palette.
- [x] Implement imports (drop/file/paste), export, sessions, settings/provider CRUD/test/select, first-run setup and assets/progress/errors/diagnostics/theme.
- [x] Use React 19, strict TS, TanStack Query, Zustand, RJSF custom widgets, Tailwind. No mock domain state in production.
- [x] Run component and browser tests against scripted real core; production build; report exact native integration.

### Task 3: MCP proxy and subscription CLI providers

**Files:** new `core/src/badshop/mcp/**`, `providers/cli_provider.py`, `providers/profiles.py`, server integration (`app.py`, `main.py`), isolated tests/fixtures.
**Interfaces:** `badshop-core mcp --connect URL --token TOKEN --actor cli:NAME` forwards tools.list/run/artifacts.get over authenticated WS. `CoreApp.set_connection(url,token)` configures proxy launch access. CLI profiles use kind `cli`, cli enum claude/codex/gemini, optional executable path; existing API kinds remain compatible.
- [x] Verify installed CLI flags and current MCP SDK docs before implementation; record discrepancies.
- [x] Test SDK client list/call/image/error and heartbeat while approvals wait; preserve actor permissions and cancellation.
- [x] Implement CLI discovery, configs scoped to private session folders, tolerant streamed events and multi-turn resume, stop/process cleanup, surfaced login/errors.
- [x] Integrate CLI turns without invoking the in-app tool loop twice; tools continue to execute only via MCP/session. Surface messages/steps/provider status.
- [x] Run offline subprocess/fixture and protocol tests; optional live checks only when credentials exist.

### Task 4: Native lifecycle and packaging

**Files:** `app/src-tauri/**`, `packaging/**`, `.github/workflows/**`, package license/metadata, release docs.
**Interfaces:** Native commands/events defined in Task 2; spawn core resource onedir, development uv fallback; stdout handshake and held stdin pipe. Use dialog/clipboard-manager/opener plugins.
- [x] Implement lifecycle tests and Rust supervisor: timeout, stderr log, graceful stdin close, crash restart at most 3 times, recoverable failure screen.
- [x] Implement PyInstaller onedir entry with freeze_support, include keyring/backend metadata and native model runtimes; smoke handshake/tools.list/find/clean exit.
- [x] Add icon/license/notices and reproducible build scripts; build Linux locally.
- [x] Add lint/test matrix and tag-only installer/PyPI release workflows; Flatpak manifest and source/bundle build tooling. Record supported architectures based on available native wheels.
- [x] Verify application build and frozen core smoke; OS-specific release tests run in CI.

### Task 5: Integration, polish and complete review

**Files:** README, diagnostics UI, third-party/license docs, roadmap/carry-forward, integration tests.
- [x] Integrate task APIs, repair mismatches, verify first-run and complete editing/save/open/replay path.
- [x] Add live smoke test harness and release checks; run available local providers without claiming unavailable-platform verification.
- [x] Capture real app screenshot for README; document installation, unsupported environment errors, unsigned installers and model licenses.
- [x] Run full Python/TS/Rust/E2E/frozen smoke checks and independent review; fix findings.
- [x] Update milestones honestly, commit coherent changes and update PR only when concrete reviewable work is ready.

## Rulings

- Existing approved design and the user's instruction authorize implementation without another design approval round.
- Work continues on a feature branch from merged PR #2. Shared edits are partitioned by file ownership; root coordinates integration.
- SDK/CLI details and release runner versions are verified against installed/current documentation; obsolete pins are changed with an explicit compatibility record.


## Validation record

- Final full Python suite: **1,473 passed**, five opt-in/platform skips,
  one network test deselected. Independent review fixes have focused regression coverage.
- Core/native: three Rust lifecycle tests; frozen core handshake, tool discovery, spawned
  face detector, save, EOF shutdown and forced-core-death worker cleanup passed.
- Frontend: strict production build, **14 component/RPC tests**, **10 real-core browser flows**,
  and built frontend under the exact native CSP. Independent review findings corrected.
- Live: Gemini 3.8 Flash and Ollama Qwen3-VL 2B vision/native tools and JSON fallback passed;
  Claude Code and Codex resumed image inspection via MCP passed. Gemini fallback initially
  timed out at 90 seconds; retry with a 180-second harness limit completed in 76 seconds.
- Gemini CLI 0.66.0 policy engine was exercised in an isolated installation; scoped badshop
  tools allowed, built-in and unrelated MCP tools denied. Old installed CLI is refused.
- Linux Secret Service: synthetic credential write/read/delete passed; no existing entry changed.
- Linux deb, AppImage extraction runner and Flatpak Platform49: visible native window,
  renderer/core connection, normal close and no surviving descendants passed.
- Python wheel includes LICENSE; source archive excludes model caches. Linux installer sizes
  about 370 MiB (.deb), 395 MiB (AppImage) and 220 MiB (Flatpak); frozen core about 795 MiB unpacked.
- BiRefNet 761×1000 cutout: 9,328 MiB peak RSS at a 12,288 MiB limit; default stays 3,072 MiB
  for lighter tools, with measured guidance at the model picker.

## Release validation and limitations

Windows/macOS frozen smoke and Windows CLI process containment run in the added CI matrix.
Actual GUI/keychain checks and BiRefNet measurements on those OSes remain release-hardware
checks. Intel macOS is excluded; supported Apple Silicon minimum is macOS 14. AppImage FUSE
mounting was not exercised (its extraction runner was). Model/CLI behavior can vary by version
and account. No tag, public release or PyPI publication is part of this development PR.

The shipped standalone Claude skill is `skills/badshop/SKILL.md`, targeting the installed CLI;
the original reference remains a parity fixture. No persistent session schema change was needed.
