# Plan 1 carry-forward: what later plans inherit

**Written:** 2026-09-27, at the end of Plan 1's final fix wave.
**For:** whoever writes Plans 2 to 6. Read this next to the spec and the roadmap
(`docs/superpowers/plans/2026-09-26-roadmap.md`) before writing your plan.

Plan 1's final whole-branch review raised these items and the controller deferred them: each
needs something that does not exist yet (sessions, the server, the agent, the UI, packaging).
Each entry gives what is missing, why it waited, and what the owning plan has to do. The IDs
refer to the review reports kept with the Plan 1 working notes: SP (spec lens), CO
(correctness), E2E (end-to-end parity), SEC (security), TRI (triage of deferred minors).

## Plan 2: sessions and local server

These are contracts. Plan 1 left the engine seams in place (`EngineResult.data`, the `Store`
protocol, `assets.URL_POLICY`), but nothing uses them yet.

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
  paths only from the UI's file picker. The registry has no way yet to hide a field from
  `llm_schema`; add one (it also serves SEC-S8).

- **SEC-S11 (second half): web text is untrusted.** Plan 1 turns control characters in remote
  titles, creators, licences and links into spaces, but the text itself still reaches the model
  as tool output, and titles and page URLs are exactly where injected instructions arrive.
  *Why deferred:* the agent context does not exist in Plan 1.
  *Plan 3 must:* mark web-originated text in tool results as untrusted data (delimited, with a
  system-prompt rule not to follow instructions inside it).

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

## Declined

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
