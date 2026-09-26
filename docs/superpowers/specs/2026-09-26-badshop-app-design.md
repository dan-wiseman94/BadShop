# badshop desktop app — design spec

**Date:** 2026-09-26 · **Status:** draft for review · **Owner:** Dan Wiseman

## 1. Summary

badshop is an open-source, cross-platform desktop app that lets any vision-capable LLM make
deliberately bad, 2005-forum-style photoshops (hard-edged cut-and-paste, Impact captions,
laser eyes, deep-frying) using a deterministic image engine, while the user watches every
step, edits any step's parameters, runs tools themselves, and optionally approves each call.

It is **not an image editor**. It is a controller for an AI-driven process: the LLM is the art
director, the engine owns the pixels, and the app is the cockpit around that loop.

## 2. Intent (what was agreed)

What Dan said:
- Audience: **public release**, cross-platform, installable.
- The app "is a way to communicate with any LLM and expose all the options and functions to
  the user. It's not an editor, it's a controller for the current AI-driven process."
- LLM access, all four in v1: **cloud API keys**, **local models**, **any OpenAI-compatible
  URL**, **existing subscriptions via CLI** (Claude Code, Codex, Gemini CLI).
- User controls, all four in v1: **see every step**, **edit & re-run steps**, **run tools
  manually**, **approve before running**.
- Architecture: **Python core + Tauri shell** (option A of three presented).
- **Session save/reopen is in v1.** **Code signing is not** (later milestone).

What this spec assumes (correct any of these in review):
- The app name stays **badshop**; the repo is `~/badshop`, licensed MIT.
- The existing engine behavior (the CLI in `reference/badshop.py`) is correct and is ported,
  not redesigned. Its style rules (§3) are product requirements.
- English-only UI in v1; single user; one session window at a time.
- The Claude Code skill keeps working by calling the packaged engine's CLI.

**Success criteria for v1:**
1. A user on Linux, Windows, or macOS installs one download, adds a provider, types
   "put Trump's head on Lincoln, deep fry it, add laser eyes", and gets the result, with each
   step visible in the timeline.
2. The same request works through each of the four provider kinds (with a capable model).
3. The user can change any step's parameters and re-run from there without the LLM, run any
   tool from the palette, and turn on approve-before-run, on every provider kind.
4. Closing and reopening a saved session restores chat, steps, and images exactly, and
   replaying it reproduces the same output pixels.
5. No image-generation model is ever invoked; every output pixel comes from the engine.

## 3. Product rules (non-negotiable)

Carried over from the CLI skill (`reference/SKILL.md`):
- Pasted pixels are untouched: nearest-neighbor scaling, hard alpha, no feathering, blending,
  color matching, shadows, or edge cleanup.
- Never route an image through an image-generation or inpainting model.
- "Bad is the deliverable": the agent fixes placement at most once or twice, then stops.
- Deterministic engine: the same inputs, parameters, and seeds give identical output bytes
  (except JPEG encoder differences across library versions, which tests pin).

## 4. Scope

**In v1:** every engine command as a tool (the 23 CLI commands in `reference/tool-catalog.md`, mapped per §5.2), the
four provider kinds, the four control modes, drag-and-drop / paste / built-in image sources,
export, session save/open, installers for Linux (AppImage, .deb, Flatpak), Windows (NSIS
.exe), macOS (.dmg, universal or per-arch).

**Out of scope for v1:** manual canvas editing (users edit parameters, never pixels
directly), image-generation models, accounts, cloud hosting, web version, mobile,
posting to social networks, code signing and notarization, auto-update, localization,
multiple simultaneous sessions, GPU inference.

## 5. Architecture

Two processes: a Python **core** that does everything, and a thin **shell** that renders it.

```
┌──────────────── Tauri 2 shell (Rust, thin) ──────────────┐
│ React + TypeScript UI                                    │
│  chat · step timeline · param forms · image viewer       │
│  tool palette · approvals · settings · sessions          │
└───────────────▲──────────────────────────────────────────┘
                │ WebSocket, JSON-RPC 2.0 + event stream
┌───────────────┴──────── badshop-core (Python) ───────────┐
│ server/     WS API on 127.0.0.1, random port + token     │
│ session/    steps, artifacts, project files, replay      │
│ tools/      registry: name → Pydantic params → handler   │
│ engine/     pixel work ported from reference/badshop.py  │
│ agent/      turn loop, approval gate, context builder    │
│ providers/  litellm_provider  (APIs, local, OpenAI-compat)│
│             cli_provider      (claude / codex / gemini)  │
│ mcp/        MCP proxy server (stdio) → core tools        │
│ cli.py      `badshop <cmd>` (CLI parity; the CC skill)   │
└──────────────────────────────────────────────────────────┘
```

Principle: **every tool call goes through `session/`, whoever makes it** (the in-app agent,
a CLI agent via MCP, or the user). That single choke point is what makes the timeline,
approvals, edits, and replay work identically for all four provider kinds.

### 5.1 `engine/`: pixel work

A port of `reference/badshop.py`, split by concern into `sources.py` (fetch, wiki, emoji,
template, clipboard), `faces.py` (YuNet + Haar), `cutout.py`, `compose.py` (paste),
`text.py` (captions, WordArt, fonts), `effects.py` (eyes, warp, flare, sparkle, watermark,
filter, censor, draw), `finish.py` (save, deepfry, animate), and `assets.py` (downloads and
caching of models and fonts).

- Functions take `PIL.Image` objects and typed parameters and return a result object:
  output images, structured data (for example face boxes), and human-readable lines (the
  CLI's `key: value` output). No file paths inside the engine, no printing, no `sys.exit`:
  errors raise `EngineError(message, hint)`.
- The pixel algorithms are ported **as is**. The only behavior changes are the ones below.
- rembg: pin the model per call (default `u2net`, alternatives `u2net_human_seg`,
  `isnet-anime`, `birefnet-general`). **Never use rembg's own default (`bria-rmbg`),** whose
  weights have historically been non-commercial. The implementer confirms each offered
  model's license before shipping it. Set `REMBG_HOME` to the app data dir before importing
  rembg; do not enable alpha matting (avoids the numba dependency).
- Asset downloads (rembg models, YuNet, Anton, Comic Neue) go to the per-OS app data dir
  (`platformdirs`) and report progress through a callback, which the UI shows.
- Randomness takes an explicit `seed` parameter everywhere (repeat scatter, sparkle, shake,
  deepfry noise), so replays are deterministic. `deepfry` gains a `seed` (default 1).

### 5.2 `tools/`: the single registry

Each tool is declared once:

```python
@tool(name="paste", category="compose", mutates=True, network=False)
class PasteParams(BaseModel):
    base: ImageRef
    piece: ImageRef
    fit_box: Box | None = None
    at: Point | None = None
    anchor: Literal["topleft", "center", "bottom"] = "topleft"
    ...
def paste(p: PasteParams, ctx: ToolContext) -> ToolResult: ...
```

- **Parameter types** beyond primitives: `ImageRef` (an artifact ID, or a new file by path or
  URL), `Point`, `Box`, `Color`, `Seed`. These produce JSON-schema `format` hints
  (`badshop-image`, `badshop-point`, `badshop-box`, `color`), which the UI renders as
  special widgets (§8.4).
- The registry generates: LLM tool definitions (OpenAI format for LiteLLM), the MCP tool
  list, the UI forms (JSON schema), and the CLI's argparse (so CLI parity is automatic).
- **Descriptions are written for LLMs**, adapted from the SKILL.md tables, including when to
  use each tool and the coordinate conventions.
- Tool coverage: every command in `reference/tool-catalog.md`, adapted as follows:
  - `-o/--out` disappears; outputs become new artifacts (§6). `save`/`deepfry`/`animate` still
    produce artifacts, and `export` writes files to disk.
  - `recipe`/`run` become session features (replay, export recipe), not tools. The CLI keeps
    them as CLI-only commands over a headless session, so the CLI still has all 23 commands.
  - `prep` stays a tool (explicit resize) even though import already does it automatically.
  - New `view` tool: returns an artifact (optionally with the coordinate grid overlay) as an
    image, so any agent can look at anything. This replaces "Read the _grid.png".
  - New `export` tool: writes a final artifact to the user's output folder (default
    `~/Pictures/badshop`, configurable), with the same never-overwrite naming as today.
- Metadata flags: `mutates` (produces or changes images), `network` (fetch, wiki, emoji,
  template), `read_only` (find, info, view). Approval policies use these (§7, Approval modes).

### 5.3 `session/`: state, artifacts, replay

**Artifacts:** immutable images stored by content hash (SHA-256 of the PNG/JPEG/GIF bytes),
with metadata: dimensions, format, producing step, source and license (for fetched images),
and a short label ("lincoln_work", "trump_head").

**Steps:** an ordered list; see the data model (§6). Each step records the tool, validated
parameters, the actor (`agent:<provider>`, `cli:<claude|codex|gemini>`, `user`), status,
output artifact IDs, the result text, timing, and errors.

**Replay:** `replay_from(step_n)` re-executes step N and every later step in order,
resolving `ImageRef`s through a remapping table: any reference to an old output of a
re-executed step points to its new output. Steps whose inputs did not change are not
re-run (a content-hash cache keyed on tool + params + input hashes). When the user
edits step N, steps N+1… are marked **stale** and replayed immediately, or only on click if
"auto-replay" is off in settings.

**Informing the agent about user changes:** anything the user did since the agent's last turn
(edited step 4, added step 9 manually, rejected a call) is summarized in a system note at
the start of the next agent turn, so the model's picture stays true.

**Working copies:** `prep` runs automatically. Any image entering the session (drop, paste,
fetch) is imported as a ≤1000 px working copy, which is the artifact every tool sees. v1
works at working-copy resolution only, exactly like the CLI, so coordinates always mean
the same thing. The full-resolution original is stored alongside for provenance only.

### 5.4 `agent/`: the in-app loop (API, local, and OpenAI-compatible providers)

One turn:
1. Build context: system prompt (the SKILL.md workflow and style rules, adapted to tools),
   the chat so far, a compact step summary, and images. Images are budgeted: the latest
   output plus any artifact the model referenced this turn, each downscaled to ≤1024 px, and
   older images replaced by text placeholders (`[image a3f9: lincoln_work, 761×1000]`) that
   the model can re-open with `view`.
2. Call the provider with the tool definitions and stream text deltas to the UI.
3. For each tool call: validate the parameters (on a validation error, return it to the model
   as the tool result, and allow at most 3 consecutive failures), apply the approval policy
   (§7, Approval modes), execute through `session/`, and return the text lines plus output images as the
   tool result.
4. Repeat until the model answers without tool calls, the user presses Stop, or the
   per-turn step budget (default 40) runs out, in which case the loop reports it and pauses.

Cancel: Stop cancels the provider request and any running tool at the next safe point.
Completed steps are kept.

### 5.5 `providers/`

**Provider profiles** (user-created, several allowed; one is active per session):
`{id, kind, label, model, api_base?, api_key_ref?, cli?, capability_overrides}`.

**`litellm_provider`** covers cloud APIs, local servers, and OpenAI-compatible URLs:
- `litellm.completion(model, messages, tools, tool_choice="auto", stream=True)`, with
  OpenAI-format tools and `image_url` blocks carrying base64 data URLs.
- Model strings: `anthropic/…`, `openai/…`, `gemini/…`, `openrouter/…`, `ollama_chat/…`,
  and `openai/<model>` plus `api_base` for any OpenAI-compatible server (LM Studio, vLLM,
  Groq…). The implementer verifies at build time that `ollama_chat/` passes images through,
  and uses the `ollama/` prefix for vision if not.
- **Capability check:** `litellm.supports_vision()` and `supports_function_calling()` when
  known. For local and custom models these are unreliable, so the profile has user-set
  "supports images" and "supports tool calls" toggles. With no vision support, the profile is
  refused with a clear explanation (the art director must see). With no native tool calling,
  a warning explains LiteLLM's JSON-mode fallback and that results will be poor.
- Streaming with tool calls: accumulate the chunks and rebuild with
  `litellm.stream_chunk_builder`. The implementer confirms that tool calls survive the
  rebuild, and falls back to non-streaming tool turns if not.
- Local-model quality mitigation: always offer the grid overlay through `view`, and put `find`
  boxes in results, so weak models copy numbers instead of estimating them.

**`cli_provider`** covers existing subscriptions. The CLI runs its own agent loop; badshop
only supplies tools through MCP and observes and gates them through `session/`:

| CLI | Launch (long-lived per session unless noted) | MCP attach | Approvals & timeouts |
|---|---|---|---|
| Claude Code | `claude -p --input-format stream-json --output-format stream-json --verbose --include-partial-messages --strict-mcp-config --mcp-config <json> --allowedTools "mcp__badshop__*"`. **Not `--bare`**, because bare mode ignores OAuth/keychain login and would lock out subscription users. | inline JSON via `--mcp-config` | Tools auto-allowed; badshop's own approval gate waits inside the tool handler. Idle timeout is 30 min on stdio servers, so send `report_progress` heartbeats every 60 s while waiting, and set `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=0` in the child env. |
| Codex | `codex exec --json -s read-only --skip-git-repo-check …` per turn; later turns `codex exec resume <SESSION_ID> --json …` | `-c` overrides for `mcp_servers.badshop.*` (unverified: confirm first). Fallback: a private `CODEX_HOME` whose `config.toml` defines the server and **links the user's `auth.json`** so the subscription login survives. | `tool_timeout_sec` default is 60 s, so set it to 3600; `default_tools_approval_mode="approve"` (badshop gates instead). Never `--full-auto` (deprecated) or `--yolo`. |
| Gemini CLI | `gemini -p <prompt> --output-format stream-json`, cwd = the session work dir; multi-turn through `--resume <uuid>` (unverified with `-p`: confirm first, else resend the transcript summary) | a workspace `.gemini/settings.json` in the session work dir with `mcpServers.badshop` (`trust: true`, `timeout: 3600000`) | `trust` on badshop's server only, never global `--yolo` (open issues report yolo still prompting). Treat as the least predictable CLI and label it "experimental" in v1. |

- **Images to CLI agents:** the user's images reach them as artifacts they open with the
  `view` MCP tool (MCP image results work in all three). Claude Code can also receive
  images inline through stream-json input content blocks; Codex through `-i`.
- The chat pane renders each CLI's stream events (text, tool use, result) in a common form.
  Unknown event types are shown raw and logged, never fatal.
- CLI detection: look up `claude`, `codex`, and `gemini` on PATH (plus the common install
  dirs, since GUI apps get a minimal PATH on macOS), show their versions, and let the user
  point at a binary manually.
- **The MCP proxy:** a CLI launches MCP servers itself over stdio, so badshop ships
  `badshop-core mcp --connect <ws-url> --token <t> --actor cli:<name>`. This small process
  forwards `tools/list` and `tools/call` to the running core over the same WebSocket API the
  UI uses. The core is the single source of truth; the proxy holds no state. It is built on
  the MCP Python SDK **v2** (`from mcp.server import MCPServer`; pin `mcp>=2,<3`), returning
  `Image` content for image outputs.

### 5.6 `server/`: the local API

- Binds `127.0.0.1` on a random free port. The core prints `{"port":…, "token":…}` as its
  first stdout line; the shell reads it. Every connection must present the token (first
  message); anything else is closed.
- JSON-RPC 2.0 requests from clients; server-pushed notifications for events (§7).
- Multiple clients at once (the UI plus MCP proxies), each tagged with an actor.

### 5.7 Shell (Tauri 2 + React + TypeScript)

- The Rust side does only this: spawn the core, read the port/token handshake, restart it on
  crash (at most 3 times, then show an error screen with the log path), kill it on exit, and
  expose native dialogs (open/save file, reveal in folder) plus clipboard image reading to
  the UI.
- **Bundling the core:** PyInstaller **onedir** (onefile would unpack hundreds of MB on every
  launch). Tauri's `bundle.externalBin` accepts single files only, so the onedir goes in
  `bundle.resources` (for example `"core-dist/"`), resolved at runtime through the resource
  dir and spawned with a plain command, not `.sidecar()`. A per-OS CI smoke test (§11)
  guards this.
- UI stack: React 19, TypeScript strict, Vite, TanStack Query for requests, Zustand for UI
  state, a JSON-schema form renderer (react-jsonschema-form with custom widgets), and
  Tailwind CSS. The UI holds no domain state beyond caches of server events.

## 6. Data model

```ts
Session  { id, name, created_at, provider_profile_id, approval_mode,
           messages: Message[], steps: Step[], artifacts: Record<ArtifactId, Artifact> }
Message  { id, role: "user"|"assistant"|"system_note", content: Part[], step_ids: StepId[] }
Step     { id, index, tool, params, actor, status: "proposed"|"approved"|"running"|
           "done"|"error"|"rejected"|"stale", outputs: ArtifactId[], result_text: string,
           data?: object /* e.g. find's face list */, error?: {message, hint},
           started_at?, finished_at?, cache_key }
Artifact { id /* sha256 */, label, width, height, format, mime,
           produced_by?: StepId, source?: {kind, url?, license?, creator?} }
```

**Project file** (`.badshop`): a zip holding `session.json` (the above, versioned with
`"schema": 1`), `artifacts/<sha256>.<ext>`, and `recipe.json` (the steps as a
parameter-only recipe, compatible with the CLI's `run`). Opening a file with a newer schema
refuses with a message; older schemas are migrated. The provider profile is referenced by
ID only; keys never go into the file.

## 7. Protocol

**Requests (client → core):** `session.new|open|save|save_as|export_recipe`,
`chat.send {text, attachments}`, `chat.stop`, `tools.list`, `tools.run {tool, params}`
(manual), `steps.edit {step_id, params}`, `steps.replay_from {step_id}`,
`steps.delete {step_id}` (the last step only in v1), `approval.respond {step_id, decision:
approve|reject|edit, params?, note?}`, `artifacts.get {id, max_px?}`, `artifacts.import
{path|bytes}`, `export {artifact_id, name?}`, `providers.list|save|delete|test`,
`settings.get|set`, `assets.status|download`.

**Events (core → client):** `message.delta`, `message.done`, `step.proposed`,
`step.started`, `step.progress`, `step.finished`, `step.failed`, `step.stale`,
`approval.needed`, `approval.resolved`, `turn.started`, `turn.finished {reason}`,
`asset.progress`, `provider.status`, `core.log`.

### Approval modes

Per session, switchable at any time:
- **Auto:** everything runs.
- **Ask for changes:** read-only tools (`find`, `info`, `view`) run; everything else waits.
- **Ask for everything.**

A waiting call shows its tool, parameters (editable before approving), and the model's
stated reason. Reject returns a "rejected by user: <note>" tool result so the model adapts.
The same gate applies to CLI agents through the MCP proxy, which blocks until the user
decides, sending progress heartbeats (§5.5).

## 8. UI

Main window, three panes, all resizable:

```
┌ badshop ─ [session name ▾] ── [provider ▾ model] ── [approval: Ask for changes ▾] ── [Export] ┐
│ Chat                     │ Viewer                              │ Steps                       │
│  user / assistant msgs   │  selected step's output (or latest) │  1 fetch   wiki "Lincoln" ✓ │
│  tool-call chips link →  │  before/after toggle, zoom 1:1/fit  │  2 find    faces ✓          │
│  approval cards inline   │  grid overlay toggle                │  3 cutout  oval ✓ (edited)  │
│  [drop/paste images]     │  face boxes overlay (from find)     │  4 paste   ⏳ awaiting OK   │
│  [message box] [Stop]    │  click-to-pick for point/box fields │  5 deepfry … stale          │
│                          │                                     │  [+ Run tool ▾]  [Replay ▸] │
└──────────────────────────┴─────────────────────────────────────┴─────────────────────────────┘
```

### 8.1 Chat
Streaming markdown. Tool calls appear as compact chips that select that step. Pending
approvals appear inline as cards (Approve / Edit / Reject). Images can be dropped or pasted
into the message box, and become artifacts attached to the message.

### 8.2 Viewer
Shows the selected step's output, or the latest one. Before/after toggle (the step's first
input vs. its output), fit / 1:1 zoom, optional pixel grid overlay, and overlays for `find`
results. GIF outputs animate.

### 8.3 Steps timeline
Each step shows its index, tool, a one-line parameter summary, actor icon (model / CLI /
user), and status. Selecting a step opens its detail drawer: full parameters in an editable
form, result text, error and hint, provenance and license for fetched images, and actions
(Apply & replay, Replay from here, Copy as CLI command).

### 8.4 Forms and the tool palette
- "+ Run tool" opens the palette: tools grouped by category with search. Choosing one opens
  its generated form; Run executes it as a `user` step.
- Widgets by format: `badshop-image` is an artifact picker (thumbnails) plus "open file";
  `badshop-point`/`badshop-box` are number fields plus a "pick on image" button that lets the
  user click or drag on the viewer to fill them (parameter entry only, not editing);
  `color` is a swatch picker. Enums become selects, ranges become sliders, and booleans
  become switches.

### 8.5 Settings
Provider profiles (add/test/delete; a key field stored in the OS keychain), CLI detection
and paths, default approval mode, auto-replay on edit, output folder, per-turn step budget,
asset downloads (status and pre-download all), theme (follow system / light / dark).

### 8.6 First run
A three-step welcome: choose a provider kind (with a one-line explanation of each), enter a
key / URL / CLI or detect one, then pre-download the core assets (about 180 MB, optional,
otherwise on first use). Ends at an empty session with example prompts.

## 9. Settings, secrets, files

- Paths via `platformdirs`: config (`settings.json`, provider profiles without secrets),
  data (models, fonts, session autosaves), cache (artifact thumbnails), logs (rotating,
  7 days).
- **Secrets** in the OS keychain through `keyring` (Keychain on macOS, Credential Locker on
  Windows, Secret Service or KWallet on Linux). If keyring raises `NoKeyringError` (Linux with
  no secret service running), offer: use an environment variable, or store the key in the
  config file after an explicit plaintext warning. Never store it silently. The PyInstaller
  spec must include keyring's backend entry-point metadata (`copy_metadata`, plus hidden
  imports for the backends).
- **Autosave:** the open session saves to the data dir after every step. On a crash, the next
  launch offers to restore it.

## 10. Error handling

- **Engine errors** (`EngineError`) become a failed step with a message and hint. The agent
  gets the same text as the tool result and can retry; the user sees it in the step drawer.
- **Provider errors** (auth, rate limit, context too long, refusal) end the turn with a
  readable banner and a "retry turn" action. Content refusals are shown as the model's
  message. The app never tries to work around a provider's policies.
- **Network tools** time out after 30 s and report which source failed; `fetch` keeps partial
  results from other sources, as today.
- **Asset downloads** can be resumed, are checksum-verified where the upstream publishes
  checksums, and show a retry action on failure.
- **Core crash:** the shell restarts it (§5.7) and reopens the autosave. Three crashes in a
  row show an error screen with the log path and a "copy diagnostics" button (versions, OS,
  last 200 log lines, no keys).
- **CLI provider failures:** a missing binary, a login needed (show the CLI's own login
  command to run), a stream parse error (show the raw line, keep the session), or the
  process exiting (the turn fails with its stderr tail).

## 11. Testing

- **Engine:** port behavior tests from the CLI session's checks. Golden-image tests with
  fixed seeds per tool (small fixture images in `core/tests/fixtures`, freely licensed). Face
  detection is tested on fixture portraits with tolerance boxes.
- **Registry:** every tool's schema is valid JSON Schema; every tool in
  `reference/tool-catalog.md` is registered (catalog parity test); the generated argparse
  accepts the documented CLI invocations from `reference/SKILL.md`.
- **Session:** replay-from-N remaps references, the cache skips unchanged steps, and save →
  open → replay gives byte-identical artifacts.
- **Agent:** a scripted fake provider (a fixed sequence of tool calls and texts) drives the
  loop; covers approval modes, validation-error retries, step budget, and stop.
- **Providers:** LiteLLM message and tool conversion tests against recorded fixtures; CLI
  stream parsers tested against recorded stream-json/JSONL transcripts for each CLI; an
  optional live smoke suite (`-m live`, needs keys or CLIs) for real providers.
- **MCP proxy:** a contract test with the MCP SDK client: list tools, call `view` → image
  content, and an approval wait that outlasts 60 s while heartbeats keep it alive.
- **UI:** Vitest for components and the form widgets; Playwright end-to-end against the dev
  build with the fake provider (send message → steps appear → edit → replay → save → open).
- **Packaging (CI):** on each OS, build the installer, launch the bundled core headless,
  handshake, call `tools.list`, run `find` on a fixture, then quit.

## 12. Build and release

- Monorepo layout:
  ```
  core/        Python package badshop (uv project; engine, tools, session, agent,
               providers, server, mcp, cli); tests
  app/         Tauri 2 project: src-tauri/ (Rust), src/ (React/TS)
  packaging/   pyinstaller spec, flatpak manifest, icons, installer assets
  reference/   the original CLI engine, skill, and tool catalog (read-only)
  docs/        specs and plans
  ```
- Python 3.12, `uv` for dependencies. Dependencies: pillow, numpy,
  opencv-python-headless>=4.8,<5 (5.x removed the Haar cascades used for cats), rembg[cpu],
  onnxruntime, litellm, mcp>=2,<3, pydantic>=2, websockets, platformdirs, keyring.
- Node 22 LTS and pnpm for the UI; Rust stable for Tauri.
- **CI (GitHub Actions):** lint and test on push; on tag, a matrix build of ubuntu-22.04
  (AppImage, deb), windows-latest (NSIS), macos-14 arm64 and macos-13 x64 (dmg), each running
  the §11 packaging smoke test. Artifacts go to a GitHub Release. Known risk: onnxruntime's
  Windows DLL loading (`onnxruntime_providers_shared.dll`) under PyInstaller; the smoke test
  catches it.
- **Flatpak:** a separate `flatpak-builder` manifest (Tauri does not produce Flatpaks), using
  the Tauri Flatpak guide's cargo/node source generators and the prebuilt core onedir as a
  module. Aim for Flathub after v1 ships; v1 attaches the `.flatpak` bundle to releases.
- The CLI (`core` installed with `uv tool install`, or `pipx`) is published to PyPI as
  `badshop`, so the Claude Code skill runs `badshop <cmd>` instead of the reference script.
- Unsigned in v1: the README documents the macOS "Open anyway" and Windows "More info →
  Run anyway" steps.

## 13. Milestones

Each ends with passing tests and something runnable.

1. **Core engine package:** port `reference/badshop.py` into `core/badshop/engine`, the tool
   registry (21 engine tools plus `view` and `export`), and the generated CLI with parity to
   the reference (all 23 commands, including `recipe`/`run`), with golden tests.
2. **Session and server:** artifacts, steps, replay/cache, project files, the WebSocket API,
   and the scripted fake provider driving the agent loop headless.
3. **LiteLLM provider:** profiles, keyring, capability checks, image budgeting, approvals;
   usable from a minimal CLI chat (`badshop chat`) before any GUI exists.
4. **Shell MVP:** Tauri app with chat, viewer, timeline, step editing and replay, tool palette,
   approvals, settings, save/open, and first run.
5. **MCP proxy and CLI providers:** Claude Code first, then Codex, then Gemini
   (experimental).
6. **Packaging and CI:** PyInstaller onedir, Tauri bundles, Flatpak, smoke tests, and the
   GitHub Release workflow.
7. **Polish for release:** error screens, diagnostics, README with screenshots, license and
   attribution notices for bundled fonts, models, and fetched images.

## 14. Risks and open questions

- **Content:** public-figure satire is the flagship use. Providers may refuse some requests;
  the app surfaces refusals honestly and never works around them. The app adds no
  identity-deception features (for example no metadata spoofing).
- **Weak local models** will place things badly or loop. Mitigations: grid views, `find`
  boxes, the step budget, and the fact that "bad" is the goal anyway.
- **CLI drift:** the three CLIs' flags and stream formats change often. Parsers stay
  tolerant (§5.5), recorded transcripts in tests pin the known formats, and each CLI adapter
  records the version range it has been tested against.
- **Installer size** of about 200–300 MB (onnxruntime + OpenCV + Python). Acceptable for v1;
  revisit (onnxruntime-only background removal, trimmed OpenCV) if users complain.
- **Unverified details** flagged above (Codex `-c` MCP overrides, Gemini `--resume` with `-p`,
  Ollama vision under `ollama_chat/`, tool calls through `stream_chunk_builder`) must each be
  confirmed by a small spike at the start of the milestone that needs it.

## Appendix A: references

- `reference/badshop.py`: the working engine and CLI (PEP 723, runs with `uv run`).
- `reference/SKILL.md`: the art-director workflow and style rules that become the system
  prompt and tool descriptions.
- `reference/tool-catalog.md`: every command and parameter, generated from the engine's
  argparse definitions; the registry parity test checks against it.
