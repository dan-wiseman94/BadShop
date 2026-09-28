# Plan 1 carry-forward: what later plans inherit

**Written:** 2026-09-27, at the end of Plan 1's final fix wave. **Updated** at the end of Plan 2
(its Task 13): every Plan 2 item below is done, and Plans 3 to 6 gained the items Plan 2 hands on.
**For:** whoever writes Plans 2 to 6. Read this next to the spec and the roadmap
(`docs/superpowers/plans/2026-09-26-roadmap.md`) before writing your plan.

Plan 1's final whole-branch review raised these items and the controller deferred them: each
needs something that does not exist yet (sessions, the server, the agent, the UI, packaging).
Each entry gives what is missing, why it waited, and what the owning plan has to do. The IDs
refer to the review reports kept with the Plan 1 working notes: SP (spec lens), CO
(correctness), E2E (end-to-end parity), SEC (security), TRI (triage of deferred minors).

## Plan 2: sessions and local server

**Done** (Plan 2, `2026-09-27-plan-2-sessions-server.md`). Where each item landed:

| Item | Done in |
|---|---|
| SP F3 manifest and progress | Task 4: `engine/manifest.py` (`ASSETS`, `status`, `download`, `ensure_rembg_model`), `assets.PROGRESS`; rembg weights download through `cached()`, so pooch never prints. Task 12: `assets.status`, `assets.download`, `asset.progress` events |
| SP F4 provenance | Task 3: `EngineResult.data["sources"]`, aligned with `outputs`; Tasks 5 and 7 store it as `ArtifactMeta.source`. Its last part (the original as the downloaded bytes) is declined: see Declined below |
| SP F15 validate / execute | Task 2: `runner.validate(name, raw, actor)`, `runner.execute(name, params, store, stem)`; `run_tool` composes them |
| SEC-S7 untrusted callers | Task 2: `runner.validate` checks the actor; Task 5: `ArtifactStore.resolve` takes ids only and never touches the disk; Task 7: `Session.export` by artifact id through `files.final_path`, `ToolSpec.writes_files`; Task 11: approvals keyed on `read_only`; Task 12: only `user` may call session, file and settings methods |
| SEC-S8 clipboard | Task 2: `FetchParams.clipboard` is user-only (the `USER_ONLY` marker in `engine/types.py`): hidden from `llm_schema`, refused from other actors |
| SEC-S2 private addresses | Task 6: `session/netpolicy.py` (`refuse_private`, `guarded`) around every tool call. Resolve-then-connect stays best effort (no address pinning) |
| SEC-S4 worker with limits | Task 10: `session/worker.py` (`WorkerExecutor`: 120 s wall clock, 3072 MB RSS watchdog, cancel, a fresh worker after any kill) |
| CO M8 prep flattens | Task 5: `ArtifactStore.import_image` keeps alpha; `prep` stays the parity tool |
| TRI T7 F3 rembg sessions | Task 4: `cutout.rembg_session` caches one session per model in the worker; `drop_sessions()` |
| Task 3 GIF handles | Task 5: imports and artifacts decode from bytes |
| The four parked residuals (Plan 1 rulings 80-83) | Task 1: `finish.GIF_MAX_STILL_MS`, `text.DOWNLOAD_RETRY_S`, `common.check_size(w, h, floor)`; the golden-output note stays under Plan 6 below |

The entries below are the record of what was asked.

- **SP F3: asset manifest and download progress.** `assets.cached(..., progress=)` exists, but no
  caller passes `progress`, and rembg's models bypass `cached()`: `cutout` calls
  `rembg.new_session`, whose pooch download prints its own tqdm bar to stderr. No API lists the
  assets (name, URL, size) that spec §7 `assets.status|download`, `asset.progress` and §8.6
  pre-download need.
  *Why deferred:* progress events belong to the server and the UI, which Plan 2 builds.
  *Plan 2 must:* add a manifest in `assets` (fonts, YuNet, the four rembg models, each with URL,
  size and hash), a process-wide progress listener that `cached()` reports to, and download the
  rembg weights through `cached()` into `REMBG_HOME/models/<m>/<m>.onnx` before `new_session`,
  so pooch finds them and never prints.

- **SP F4: structured provenance for fetched images.** Each candidate's URL, title, licence and
  creator reach the result only as caption text (`(WxH) title [openverse, CC BY 2.0, by X]`).
  `EngineResult.data` is `{}` for fetch, wiki, emoji and template; Commons searches never request
  a licence (`iiprop=url|mime|size`); JPEG candidates are re-encoded, so "the original stored for
  provenance" (spec §5.3) is not the downloaded bytes.
  *Why deferred:* nothing consumes it until sessions store artifacts (spec §6 `Artifact.source`).
  *Plan 2 must:* add per-output provenance (for example `data["candidates"]` keyed by output
  key, or an `Output.source` field). Never parse it from captions. CLI stdout stays as it is.

- **SP F15: validation is fused with execution.** `run_tool(name, raw, store)` validates and runs
  in one call; the only way to validate alone is the private `_explain`.
  *Why deferred:* only the approval gate (spec §5.4: validate, let the user edit, then run) needs
  the split.
  *Plan 2 must:* expose `validate(name, raw) -> Params` and `execute(name, params, store)`, and
  keep `run_tool` as their composition for the CLI.

- **SEC-S7: the Store contract for untrusted callers.** In the CLI every image field is a path,
  and `FileStore.load` opens any path, which is right for a user typing commands. If a model
  could pass paths, `view` would send any private photo to the provider, `info` would be a file
  existence oracle, and `export` would copy any file into Pictures.
  *Why deferred:* Plan 1 has no untrusted caller; Plan 2 introduces the model.
  *Plan 2 must:* accept only artifact IDs of the current session from `agent:*` and `cli:*`
  actors; take paths only from the user (file picker, drop, CLI argument) and URLs only through
  `fetch`; answer an unknown ref with one "no such artifact" error that never touches the disk;
  make `export` take an artifact ID and write through `FileName` into the output folder; key the
  approval gate on `read_only` rather than `mutates` (`export` has `mutates=False` but writes a
  file), or add a `writes_files` flag; import user files with `load_image(..., formats=...)`
  without EPS (SEC-S1).

- **SEC-S8: the clipboard is user input.** `fetch clipboard=true` is in the model-facing schema.
  A steered model could read an image on the clipboard (a password-manager screenshot) into the
  session, or make `fetch` GET a link on it (one-click confirm or login links), and the link,
  tokens included, returns to the model as `clipboard holds a link: <url>`.
  *Why deferred:* the CLI user owns their clipboard; the risk starts with a model caller.
  *Plan 2 must:* import the clipboard only as a `user` step (the UI's paste, spec §8.1), and
  either drop `clipboard` from the schema the model sees or always require approval for it,
  showing what will be read.

- **SEC-S2 (second half): a private-address policy.** Plan 1 limits every fetch and redirect hop
  to http(s) and calls `assets.URL_POLICY(url)` on the first URL and on every redirect hop, but
  the CLI leaves the hook unset.
  *Why deferred:* in the CLI the user types the URL; in Plan 2 pages, APIs and the model choose
  URLs, and the difference between "connection refused" and "HTTP 404" turns `fetch` into a LAN
  scanner.
  *Plan 2 must:* install a `URL_POLICY` for URLs the user did not type (og:image, API results,
  redirects, any model-supplied `query`) that resolves the host and refuses private, loopback,
  link-local, reserved and multicast addresses on every hop. Resolve-then-connect is best effort
  against DNS rebinding; pin the connection to the checked address if that matters. Show the
  full URL on the step in the UI.

- **SEC-S4 (second half): a tool worker with limits.** Plan 1 bounds every parameter and budgets
  image sizes (`common.MAX_WORK_PIXELS`), but legal inputs can still take many seconds (the
  security review timed `animate spin frames=120 fry=5` at 16 s), and a crash in a native
  library would take the core down.
  *Why deferred:* the one-shot CLI can be interrupted with Ctrl-C; a long-lived core cannot.
  *Plan 2 must:* run tools in a worker process with a wall-clock limit and a memory limit, and
  treat any exception other than `EngineError`, or a killed worker, as a failed step (spec §5.4's
  "cancel at the next safe point" needs this too). Do not use `RLIMIT_AS`: under a 4 GB
  `ulimit -v`, `import cv2` segfaults. Use a cgroup on Linux, a Job Object on Windows, or an RSS
  watchdog. The worker's limit also covers what Plan 1 left open: `download_candidates` has no
  overall deadline across its up to 24 sequential requests.

- **CO M8: `prep` flattens transparency.** `basic.prep` runs `fit(to_rgb(image))`, which turns a
  transparent emoji or sticker into an opaque one (usually black behind). That is byte parity
  with the reference, which is why SKILL.md says to skip prep for emoji.
  *Why deferred:* it only matters when something imports every image through a working copy.
  *Plan 2 must:* not reuse `basic.prep` for session imports (spec §5.3). Import with
  `fit(img.convert("RGBA") if has_alpha(img) else to_rgb(img))`, as `view` does, and keep `prep`
  as the parity tool.

- **TRI T7 F3: one rembg session per call.** `cutout` builds a new `rembg.new_session` on every
  call, reloading about 170 MB (1 to 2 s).
  *Why deferred:* harmless in the one-shot CLI.
  *Plan 2 must:* cache sessions per model in the long-lived process (and drop them under memory
  pressure).

- **Task 3: GIF file handles.** `load_image(path)` on a GIF keeps the file open for later frames
  until the image is closed. The CLI accepts this (it exits); the test suite closes what it
  loads, and pytest now fails on leaked handles.
  *Why deferred:* Plan 2 imports from bytes, which holds no file.
  *Plan 2 must:* import through `load_image(bytes)` (as `try_image` already does), or close
  loaded images.

## Plan 3: LiteLLM provider and agent

- **SP F14: the finish tools describe CLI file semantics.** `save` says "Saved to the user's
  output folder", and `export` says "save and deepfry already do this". In the app these tools
  produce artifacts, and only `export` writes files (spec §5.2), so an in-app agent would claim a
  file exists that does not.
  *Why deferred:* the CLI does not read `description` (it uses `summary`); the words depend on
  Plan 2's artifact semantics.
  *Plan 3 must:* reword the `save`, `deepfry`, `animate` and `export` descriptions in
  `tools/catalog.py` for sessions.

- **SP F16 / SEC-S9 (second half): fonts as an enum.** `text.font` is a free string: a file name
  or a path, resolved inside the engine (spec §5.1 says no paths in the engine). Plan 1 refuses
  wildcards and `..`, and searches names literally, but a model can still probe whether an
  absolute font path exists ("isn't a font file" against a silent fallback).
  *Why deferred:* the enum has to be built from the fonts the running app discovers.
  *Plan 3 must:* offer the model only plain font names from an enum of discovered fonts, and take
  paths only from the UI's file picker. Plan 2 added the way to hide a field from the model:
  `json_schema_extra={USER_ONLY: True}` drops it from `llm_schema` and refuses it from every
  actor but `user` (as `FetchParams.clipboard` does). The marker lives in `engine/types.py`, which
  engine modules such as `engine/text.py` import it from (`tools/registry` re-exports it, but the
  engine must not import `tools`).

- **SEC-S11 (second half): web text is untrusted.** Plan 1 turns control characters in remote
  titles, creators, licences and links into spaces, but the text itself still reaches the model
  as tool output, and titles and page URLs are exactly where injected instructions arrive.
  *Why deferred:* the agent context does not exist in Plan 1.
  *Plan 3 must:* mark web-originated text in tool results as untrusted data (delimited, with a
  system-prompt rule not to follow instructions inside it).

- **Plan 2: real providers.** Plan 2 drives the turn loop with `agent/fake.ScriptedProvider`
  only; with no script set, `chat.send` answers "no model provider is set up yet".
  *Plan 3 must:* implement `agent/provider.Provider` (`async complete(messages, tools, on_delta)
  -> Reply`, OpenAI chat format) with LiteLLM, add provider profiles, keyring secrets, capability
  checks and the `providers.*` RPC methods, and give each provider its actor name
  `agent:<provider>`.

- **Plan 2: image budgeting.** `agent/context.build_messages` gives the model images only as text
  placeholders (`image_placeholder`: `[image a3f9c1d2: lincoln_work, 761x1000]`).
  *Plan 3 must:* add spec §5.4's budget: the latest output and any artifact the model referenced
  this turn as image parts downscaled to at most 1024 px, older ones as placeholders the model
  reopens with `view`.

- **Plan 2: the system prompt is a placeholder.** `agent/context.SYSTEM_PROMPT` only states the
  product rules and that image refs are artifact ids.
  *Plan 3 must:* replace it with the prompt adapted from `reference/SKILL.md` (spec §5.4), and
  reword the finish tools' descriptions (SP F14 above) in the same pass.

- **Plan 2: tool results are the CLI's lines.** The model's tool result is
  `session/session.result_text(step, artifacts)`: artifact lines plus the tool's `lines`, and `find`'s
  lines carry CLI flag syntax (`--fit-box`, `cutout --oval --box`).
  *Plan 3 must:* also give the model the step's `data` (JSON: `find`'s boxes and points), so it
  copies numbers instead of reading CLI hints.

- **Plan 2: no `provider.status` events.** Spec §7 lists `provider.status`, but Plan 2's only
  provider is the scripted one, and nothing sends the event.
  *Plan 3 must:* define its payload and send it from the real providers (for example a missing
  key, a failed capability check, a local server that does not answer).

- **Plan 2: no retry-turn method.** Spec §10 ends a turn that hits a provider error with a
  banner and a "retry turn" action. Plan 2's loop already ends such a turn with
  `turn.finished {"reason": "provider_error", "error"}` and leaves `SessionData.transcript` as
  it stood (the user's message last), but no method runs the turn again.
  *Plan 3 must:* add that method (for example `chat.retry {}`) together with the real provider
  errors.

- **Plan 2: no images in the transcript.** `SessionData.transcript`, the provider-format history
  the agent resumes from, is saved inside `session.json`, and a project whose `session.json`
  passes 16 MiB (`session/project.MAX_SESSION_BYTES`) can't be saved ("too big to open again").
  Plan 2's transcript holds text only (images appear as `image_placeholder` text).
  *Plan 3 must:* never put base64 images in `SessionData.transcript`: keep artifact ids or
  placeholders there, and build the image parts from the artifacts each time it sends a request.

## Plan 4: desktop shell MVP

- **SP F11: arrows and lines are typed as boxes.** `draw.arrow` and `draw.line` are `Box`
  (format `badshop-box`), but they are directed segments: a box picker that normalises corners
  would reverse an arrow drawn right to left.
  *Why deferred:* nothing builds widgets from formats yet.
  *Plan 4 must:* add a `Segment` type with its own format (for example `badshop-segment`) before
  building form widgets on format names, and update the pinned formats in
  `tests/test_catalog_parity.py`.

- **E2E M3: the generated `-h` drops defaults and ranges.** The reference's help said
  "JPEG quality 1-95 (default 35)" and `--level 1-5`; the generated parser prints the LLM
  description without defaults, bounded ints show `LEVEL` instead of a range, and out-of-range
  values exit 1 with "bad parameters" instead of argparse's 2.
  *Why deferred:* polish; every value is still validated with a clean error.
  *Plan 4 (or whoever next touches `cli/argparse_gen.py`):* append `(default X; A-B)` from each
  FieldInfo, and consider `choices` for small bounded int ranges, as the reference had.

- **Plan 2: talking to the core.** `badshop-core serve` prints exactly one stdout line,
  `{"port": N, "token": "<token>"}`, then points stdout at stderr, so the log (and anything a library
  prints) is on stderr. A connection's first message is the hello with the token and actor
  `user`; replies can come out of order (requests run concurrently); messages go up to 64 MiB.
  Closing a connection cancels the requests it is still waiting on (a session call already
  running finishes, and the reconnected UI sees its step). When the last `user` connection
  closes, the core stops a running turn and rejects pending approvals, so a reload of the webview
  ends the turn. SIGINT and SIGTERM stop the core cleanly (clients get 1001, a running tool is
  stopped, the session is autosaved), and the core installs those handlers before it prints the
  handshake line. When its stdin is not a terminal, the core also stops that way once stdin
  reaches end of file, so a core whose shell died without stopping it stops too (spec §5.7).
  *Plan 4 must:* spawn the core with a stdin pipe that the shell holds open for the core's whole
  life and never writes to (not `/dev/null`, which stops the core at once), read the handshake
  line, give the token only to the webview, call `session.get` after every (re)connect to
  rebuild the UI's state, and log stderr (spec §9).

- **Plan 2: restoring the autosave.** The session autosaves to `autosave/session.badshop` in the
  data folder after every change. When the core starts, it sets the last run's autosave aside
  (`session/project.claim_autosave()` moves it to `autosave/previous.badshop`, so this run's
  first change can't overwrite it); the snapshot reports that path as `restorable` (`null` when
  there is none), and the user-only `session.restore {}` opens it as an unsaved session
  (`path: null`).
  *Plan 4 must:* show spec §9's offer to restore it when `session.get` after launch has
  `restorable`, and call `session.restore` if the user takes it (after restarting a crashed
  core, spec §10, call it without asking).

- **Plan 2: two additions to spec §7.** The event `step.deleted {"step_id"}`: `steps.delete`
  sends it once the step is gone (Task 8's `delete_last`; the step's artifacts stay in the
  session). And the user-only method `session.restore {}` with the snapshot key `restorable`
  (the entry above). Spec §7 does not list either yet.
  *Plan 4 must:* drop the step from the timeline on `step.deleted`, and treat both as part of
  the protocol.

- **Plan 2: no `step.progress` events.** Spec §7 lists `step.progress`, but Plan 2 never sends
  it: a step announces `step.started`, then `step.finished` or `step.failed`. Downloads inside a
  tool (the first cutout fetching its model) already report `asset.progress {name, done, total}`.
  *Plan 4 must:* show a running step without it (for example its elapsed time), or add it: the
  worker already forwards download progress to the core over its pipe (Task 10), and a tool's
  own progress could travel the same way and leave through `Session`'s `emit`.

- **Plan 2: asset downloads restart from zero.** Spec §10 says asset downloads can be resumed.
  `assets.cached()` downloads into a new `.part` file every time, so an interrupted download
  starts over (about 973 MB for birefnet-general).
  *Plan 4 must:* with spec §8.6's first-run pre-download, make downloads resumable (keep the
  partial file, continue it with an HTTP Range request, check the hash at the end).

- **Plan 2: `assets.download` can't be cancelled mid-file.** It runs `manifest.download` in a
  thread that nothing can stop: a client that disconnects, or a cancelled request, leaves the
  download running to the end of the file.
  *Plan 4 must:* add a cancel (for example a flag that `cached()` checks between chunks, set by
  an `assets.cancel {name}` method) before it offers a Cancel button on a download.

- **Plan 2: the `approved` step status is unused.** Spec §6 lists `approved`, but Plan 2 moves
  an approved step from `proposed` straight to `running` and announces the decision with
  `approval.resolved {"step_id", "decision", "note"}`. The status still exists
  (`session.RUNNABLE` accepts it, and a step saved as `approved` reopens as `error`).
  *Plan 4 may:* use it (for example for a step approved but queued behind a running one); until
  a plan does, the UI must not wait for a step to become `approved`.

## Plan 5: MCP proxy and CLI agents

- **Plan 2: the proxy's side of the API.** The WebSocket accepts the hello actors `cli:claude`,
  `cli:codex` and `cli:gemini` (`server/ws.ACTOR`). Those connections receive every event and
  may call only the methods open to any actor (`tools.list`, which gives them `llm_schema`,
  `tools.run`, which runs as their actor, and `artifacts.get`); the rest answer `-32001`. A CLI
  actor's `tools.run` already waits on the approval gate like the in-app agent's calls (spec §7),
  and if the proxy disconnects while it waits, the step is rejected.
  *Plan 5 must:* add `badshop-core mcp --connect <ws-url> --token <t> --actor cli:<name>` as a
  second subcommand in `server/main.py`, and keep the MCP tool call alive (progress
  notifications or heartbeats) while an approval takes minutes.

## Plan 6: packaging and release CI

- **SEC-S12: dependency floors.** `pillow>=10.1`, `numpy>=1.26` and
  `opencv-python-headless>=4.8,<5` let a PyPI install resolve much older image decoders (which
  get security fixes in most releases), while the lock tests Pillow 12.3.0.
  *Why deferred:* only a PyPI install ignores the lock, and publishing is Plan 6.
  *Plan 6 must:* raise the floors to the tested minor versions before the first PyPI release,
  and add a scheduled CI job that re-locks and runs the suite.

- **TRI T1 F1: the lock cannot install on Intel macOS.** onnxruntime 1.30.0 has no sdist and
  ships macOS wheels for arm64 only; numba 0.67.0 and llvmlite 0.49.0 likewise. The spec's
  release matrix includes a `macos-13` x64 dmg. Pinning onnxruntime alone would not help:
  `rembg[cpu]` hard-depends on pymatting, which pulls numba and llvmlite (about 60 MB), even
  though badshop never enables alpha matting (spec §5.1's "avoids the numba dependency" holds
  at run time, not at install time).
  *Why deferred:* Plan 1's CI is ubuntu only.
  *Plan 6 must:* drop Intel macOS, or add `[tool.uv]` constraints to versions that still ship
  x86_64 macOS wheels; and budget the installer size for numba.

- **TRI T1 F3: LICENSE is not in the wheel.** It sits at the repository root, outside the
  `core/` project, and PEP 639 `license-files` cannot reference `..`; the built wheel's METADATA
  says `License-Expression: MIT` with no licence file.
  *Plan 6 must:* add `core/LICENSE` (a copy or symlink) so hatchling picks it up, and ship the
  third-party notices in the bundles.

- **Golden outputs and the lock.** `tests/test_golden.py` pins every local tool's output bytes
  against `tests/fixtures/golden.json`. When a re-lock moves Pillow, NumPy, OpenCV or
  onnxruntime on purpose, regenerate with `cd core && uv run python tests/fixtures/make_golden.py`
  and review which cases moved. The goldens were made on one machine (AMD Zen 3, AVX2, Arch
  Linux); they held with OpenCV's SIMD off, NumPy limited to its baseline SIMD, and 1, 2 or 4
  threads, but no machine with AVX-512 has run them yet. If the first CI run (or a release
  runner) fails only in `test_golden`, compare that runner's CPU before regenerating.

- **Plan 2: the tool worker is a spawn-context process.** `session/worker.py` starts a fresh
  Python for tools; a frozen core would start itself again instead.
  *Plan 6 must:* call `multiprocessing.freeze_support()` first thing in the frozen entry point,
  and keep the per-OS smoke test running one tool (spec §11 runs `find`), which proves the
  worker starts.

- **Plan 2: stopping the core on Windows.** `badshop-core serve` stops cleanly on SIGINT and
  SIGTERM (`loop.add_signal_handler`, or `signal.signal` where the event loop has no signal
  handlers). Tauri kills a child with TerminateProcess on Windows, which skips the clean stop;
  the session is autosaved after every change, so nothing is lost. Closing the core's stdin pipe
  (Plan 4 spawns it with one) is a clean stop on every OS, Windows included.
  *Plan 6 must:* check on each OS that killing the core leaves no worker process behind.

- **Plan 2: birefnet-general's memory is unmeasured.** The tool worker stops a tool whose RSS
  passes 3072 MB (Task 10; the `tool_memory_mb` setting). In Task 4's prototype a u2net session
  took about 370 MB and its first `remove()` about 216 MB more; birefnet-general's weights are
  5.5 times u2net's (about 973 MB), and nobody has run it under the limit yet.
  *Measure it* when a plan first uses the model (a model picker, say), and *Plan 6 must* have
  done so at the latest: a cutout with `model=birefnet-general` on a 1000 px working copy, in the
  worker, on each release OS. If it passes 3072 MB, raise the default limit or say what the model
  needs where the user picks it.

## Whichever plan first changes the project file

- **Plan 2: no schema migrations yet.** `session.json` carries `"schema": 1`
  (`session/models.SCHEMA`), and `project.open_project` refuses a newer schema. Spec §6 says
  older schemas are migrated, but nothing older than 1 exists, so there is no migration code.
  *That plan must:* bump `SCHEMA`, migrate schema 1 files when it opens them, and test the
  migration with a project saved at schema 1.

## Declined

- **SP F4 (last part): the original is the downloaded bytes.** Plan 2 stores a fetched picture
  as a working copy plus the tool's full-size output as its original (Task 7), and that output is
  the engine's encoding (JPEG candidates are re-encoded), not the bytes the server sent.
  Accepted: the provenance itself (`kind`, `url`, `page`, `title`, `license`, `creator`) is in
  `ArtifactMeta.source`.

- **E2E M1: 0 as "unset" for optional flags.** The reference read `a.sticker or <default>`, so
  `--sticker 0`, `--size 0`, `--frames 0` and similar meant "use the default". The port rejects
  them with a clean "bad parameters" error. Ruling 7.5 stands: the bounds are explicit and every
  such value fails cleanly.

## Also worth knowing (from the final review and the fix wave, not deferred findings)

- `tests/memstore.py` returns the pre-encode image on `load`, while `FileStore` writes
  `Output.encode()` bytes and loads them back. For JPEG and GIF outputs a chained step therefore
  sees different pixels. A session store must copy FileStore's encode, bytes, `load_image` path,
  not MemoryStore's.
- `run_tool`'s stem comes from the image ref (`PurePath(ref).stem`), so session stems will be
  artifact hashes unless the session store maps them to labels.
- `http_get`'s deadline covers the body only; the status line and headers are bounded by the
  10 s per-read timeout, so a server trickling headers could exceed 30 s. The Plan 2 worker's
  wall-clock limit covers it.
- A fetched image between about 89 and 179 megapixels makes Pillow print a
  `DecompressionBombWarning` before the 64 Mpx check refuses it. It is cosmetic; silencing it
  with `warnings.catch_warnings` is not thread-safe, so leave it to the worker.
- A rotated paste (`expand=True`) can reach about twice the 50 Mpx budget after the check; it is
  bounded.
- `find` result lines contain CLI flag syntax (`--fit-box`, `cutout --oval --box`), because
  `lines` are the CLI's output (spec §5.1). Give models `data`.
