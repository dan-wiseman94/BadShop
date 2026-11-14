# UI platform and delivery architecture audit

This appendix audits the React interface, frontend state and protocol contracts, Tauri shell, native integration, packaging, release delivery, and related verification at [`fb1ad675546bd466d5578fbf324a72361458a619`](https://github.com/dan-wiseman94/BadShop/tree/fb1ad675546bd466d5578fbf324a72361458a619). Recommendations describe future work; they have not been implemented.

**Recommendation:** retain React, Tauri, and the Python core. Substantially redesign the frontend/core contract, document projection, bounded media delivery, and ownership of UI lifecycles. A framework rewrite would leave the principal problems intact while putting mature recovery and deterministic editing behavior at risk.

The audit inspected current source and tests. It did not run application suites, build installers, exercise live providers, measure interactive performance, or perform assistive-technology testing. One narrow PowerShell parser probe reproduced a copied-command escaping defect without executing BadShop. Source-confirmed properties, reproduced behavior, and untested hypotheses are distinguished below.

## Current ownership

The renderer talks directly to the Python core over an authenticated loopback WebSocket. A singleton RPC client owns pending request callbacks and socket generations. TanStack Query caches core responses; a handwritten event reducer also changes the session cache. Zustand owns selection, coordinate picking, connection status, notices, and appearance. Component state owns drafts and local operations. Rust supplies process supervision, native dialogs, clipboard, opening/revealing files, diagnostics, and signed updates.

This is a reasonable foundation. The difficulty is within those boundaries: the Session-shaped cache mixes persisted state with transient text, consumers subscribe broadly, event contracts are weakly typed, and a few components coordinate many independent lifecycles.

| Concern | Current owner | Assessment |
| --- | --- | --- |
| Request lifecycle | [rpc.ts](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/rpc.ts) | Good generation/authentication guards; incomplete runtime result validation and operation outcome semantics. |
| Document projection | [data.ts](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/data.ts) | Increasingly expensive and difficult to prove correct across delayed snapshots/events and replacement. |
| Selection/presentation | [store.ts](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/store.ts) | Small presentation store is appropriate; some tool semantics are inferred rather than declared. |
| Save/close/replacement | [sessionActions.tsx](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/sessionActions.tsx) | Valuable revision guards and honest disconnected-cache handling. |
| App lifecycles | [App.tsx](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/App.tsx) | Too many independently changing responsibilities share one owner. |
| Advanced forms | [ToolForm.tsx](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/ToolForm.tsx) | Registry schemas and replay-draft conflict handling are strengths. |
| Native lifecycle | [supervisor.rs](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src-tauri/src/supervisor.rs) | Explicit ownership/shutdown; improve diagnostics bounds and platform bridges. |
| Update networking | [update_policy.rs](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src-tauri/src/update_policy.rs) | Correctly consults authoritative core policy through a cancellable lease. |
| Publication | [release_gate.py](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/packaging/release_gate.py) | Strong exact-candidate integrity; improve evidence automation and sustainable platform coverage. |

## Strengths to preserve

React does not implement another pixel engine. Tauri supplies OS integration while Python owns editing. Moving language/framework would not remove the need for versioned requests, bounded images, state reconciliation, or trustworthy recovery.

[`RpcClient`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/rpc.ts#L43) retires obsolete socket generations, authenticates before calls, and settles pending requests. [`startCore`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/data.ts#L301) distinguishes reconnection from a restarted core and retains drafts until recovery succeeds. [`useSessionActions`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/sessionActions.tsx#L53) checks revisions around dialogs and save/replacement. Preserve these as behavior invariants.

ToolForm uses registry schemas and merges drafts against replay changes, including explicit conflict resolution. Keep its [schema handling](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/ToolForm.tsx#L13) and [draft reconciliation](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/ToolForm.tsx#L360). Curated quick controls and advanced generated forms should use the same core commands.

The current [CSP](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src-tauri/tauri.conf.json) excludes `unsafe-eval`; forms use an eval-free validator. Historical audit text about unsafe-eval is obsolete. Native [capabilities](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src-tauri/capabilities/default.json) enumerate explicit dialogs/clipboard/open/reveal operations. Native update HTTP obtains an actor-scoped [core policy lease](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src-tauri/src/update_policy.rs#L98), stops on lost connection, and drops HTTP before acknowledging cancellation. Do not reintroduce a separate frontend settings authority.

Release controls already include locked-dependency audits, immutable Action pins, SBOM/license notices, checksums, provenance attestations, signed updates, exact build identity, candidate acceptance, and immutable published bytes. Preserve [asset validation](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/packaging/release_gate.py#L86), [acceptance validation](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/packaging/release_gate.py#L150), and [provenance verification](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/packaging/release_gate.py#L201). This source audit does not verify live repository protections or published artifacts.

There is useful accessibility groundwork: keyboard pane resizers, focus-visible styles, labels, density/text scaling, reduced motion, and still-frame previews. Tests exercise actual browser/core persistence journeys. Windows installer checks include native import/save/open, dirty-close cancellation, and output comparison. Documentation correctly distinguishes browser, native debug, installed, and live-provider evidence.

## Findings and improvements

Priorities below indicate architectural sequencing, not that every risk is an observed runtime defect.

### UI-01 Complete the protocol contract

**Source-confirmed, high priority.** The [generator](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/scripts/generate_wire_types.py#L9) only emits Artifact, Step, and Message. Session, request/result pairs, and CoreEvent are maintained separately in [types.ts](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/types.ts#L12). CoreEvent is a string plus generic dictionary. [rpc.ts](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/rpc.ts#L90) parses JSON and resolves results without method-specific validation.

A Python field/nullability change or misspelled event can compile successfully in TS and fail only at runtime. Introduce Python-owned public request/result/event schemas and a declarative method registry associating name, authorization, handler, schemas, and cancellation semantics. Generate discriminated TS event unions and the small Rust contract where useful. Keep validation authoritative rather than hand-writing it twice.

Acceptance: every registered public method/emitted event is represented; CI checks generation; malformed results produce useful protocol errors; protocol version is separate from package version. Avoid permanent multi-version plumbing where bundled shell/core always ship together.

### UI-02 Make event and snapshot identity explicit

**Source-confirmed absence of identity; race remains a hypothesis, high priority.** [CoreApp._own](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/app.py#L246) documents reusable s1 IDs and events with no session ID. It guards ownership at emission time. [_emit](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/app.py#L338) schedules delivery; [RPC replies](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/ws.py#L74) and notification pumps take different paths to the outbox. The UI [merges events](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/data.ts#L224) into its current Session. Snapshot reconciliation handles streamed text, but does not reject older document revisions.

Reproduce a delayed old-session notification delivered after replacement, and an older snapshot delivered after newer events. Current guards reduce these risks, but the wire messages cannot prove ownership. Add core-instance, document, timeline/branch, operation/turn, event sequence, and revision identities where relevant. Reject foreign/old state and resync on a detected gap.

Acceptance: delayed-subscriber/snapshot regressions, rapid branch switches, reconnect and restore cannot contaminate the new document; gaps request a fresh snapshot rather than silently losing state.

### UI-03 Separate streaming from the document projection

**Source-confirmed scaling property, high priority.** [Every text delta](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/data.ts#L184) updates the complete Session query. Most events [invalidate session.get](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/data.ts#L295), and [every action](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/data.ts#L157), including reads, does so too. Many panes subscribe to the whole Session.

This can multiply rendering, JSON serialization/transfer, and reconciliation during small changes. No latency regression was measured. Introduce an immutable indexed document projection, keep live text/progress/request state separate, and use per-entity selectors. Apply deltas; reserve snapshots for load/reconnect/gaps and justified complex transitions. Replace prefix-based invalidation with explicit resource effects. TanStack Query/Zustand can remain where useful.

Acceptance: tokens do not fetch/rerender unrelated history; reading settings does not fetch a full document; completion/error/reconnect and revision-conflict behavior remains correct.

### UI-04 Bound history rendering

**Source-confirmed, high priority.** [Timeline](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/Timeline.tsx#L112) renders all steps. [Chat](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/Chat.tsx#L148) renders all messages/Markdown and [repeatedly searches all steps](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/Chat.tsx#L209). [Viewer](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/Viewer.tsx#L341) mounts every thumbnail and performs O(A²) nested filtering. [ImagePicker](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/ToolForm.tsx#L85) repeats it. [App](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/App.tsx#L628) keeps quick and advanced panes mounted.

Build stepById and artifact/producer indexes once per relevant change. Memoize static messages, batch live text presentation, window long lists, and retrieve images on visibility. Preserve selected/approval rows, scroll anchors, keyboard focus, and screen-reader access. Give hidden drafts explicit owners rather than preserving them by mounting every feature.

Acceptance: representative long sessions meet agreed DOM/request/latency budgets; quick/advanced switching preserves intended drafts without unnecessary active subscribers.

### UI-05 Give media an explicit memory budget

**Source-confirmed representation, high priority.** [useArtifact](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/data.ts#L399) caches base64 payloads per image/thumbnail/frame; [imageUrl](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/data.ts#L413) creates data URLs. [Thumbnails](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/Viewer.tsx#L12) mount eagerly. Query garbage collection is not a byte-budget policy.

Bytes can coexist in Python buffers, JSON, JS strings and decoded surfaces; still-frame browsing adds representations. Benchmark binary transport versus base64. Keep metadata in JSON; consider authenticated loopback binary endpoints or artifact-specific Tauri protocol grants, never arbitrary filesystem paths. Cache Blob/object URLs by hash/representation, charge bytes, revoke URLs, and cancel obsolete reads. Budget full images, thumbnails, frames and previews separately.

Acceptance: repeated browsing reaches a stable memory plateau; superseded requests settle safely; eviction never deletes authoritative bytes; exports/pixels remain identical; reduced motion remains respected.

### UI-06 Fix the source-health event mismatch

**Confirmed source defect, medium priority.** [data.ts:298](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/data.ts#L298) listens for step.done, while the session emits [step.finished](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/session.py#L386). [Source health](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/app.py#L921) is derived from step results. Agent completion therefore misses this invalidation. Manual tools.run has a separate path, so not every source-health update is broken. Correct it, add a focused completion regression, and let generated event unions prevent recurrence.

### UI-07 Generate CLI text for an explicit shell

**Source and parser reproduction, medium priority.** [cliCommand](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/Timeline.tsx#L32) uses POSIX apostrophe escaping on every platform. The copy action [exports input files first](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/Timeline.tsx#L243); hashes are not incorrectly used as filenames. [Tests](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/tests/cli.test.ts) assert Linux-shaped strings.

Caption `it's` produces a fragment like `'--text=it'\''s'`. PowerShell's parser returned `TerminatorExpectedAtEndOfString`. The probe parsed text only. Supply canonical argv from the core CLI contract and render POSIX/PowerShell forms explicitly; an argv/recipe export avoids shell text when unnecessary. Keep input-export side effects clear.

Acceptance: actual argv roundtrips for spaces, apostrophes, quotes, backticks, newlines, Unicode and leading hyphens in supported shells; correct positional/flag semantics; input files exist with expected bytes.

### UI-08 Preserve recovery when rendering fails

**Source-confirmed, medium priority.** [main.tsx](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/main.tsx#L7) has no ErrorBoundary, and none was found elsewhere. App [directly accesses localStorage](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/App.tsx#L105) despite guarded [preference helpers](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/appearance.ts).

A render exception can remove workbench and recovery controls together. Denied storage during initial reads is one trigger; ordinary native storage usually works. Add a root recovery boundary and feature boundaries, retain bounded diagnostics/controlled renderer reload, and centralize safe preferences. Keep native close/recovery policy outside the failing feature/App subtree or explicitly reinstall it in the fallback: the present close listener belongs to useSessionActions and is removed on unmount. Do not automatically restart the core for every renderer exception.

Acceptance: injected secondary failures leave the document usable; root failure leaves useful recovery; a subsequent native close still requires a safe explicit decision; saved/recoverable data is retained; unavailable preferences fall back safely.

### UI-09 Separate independent UI lifecycles

**Source-confirmed, medium priority.** [App](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/App.tsx) owns startup/readiness, imports, paste/drop, shortcuts, modals/focus, appearance, updates, layout and drafts. [Studio](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/Studio.tsx#L39) combines discovery, import, library, branching and ten tabs. [Settings](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/Settings.tsx) joins profiles, preferences, assets, updates and onboarding. File length is not itself the defect; joined lifecycles are.

Extract connection/import/appearance/shortcut/modal owners. Give materials, library, branches and creative features explicit draft lifetimes. Code-split secondary panels only with useful loading/failure states and measured benefit. Move responsibility, not just files.

Acceptance: tab navigation deliberately preserves drafts; replacement clears document-owned drafts; late imports cannot attach to another document; independent features no longer require editing unrelated application lifecycle code.

### UI-10 Use one accessible dialog model

**Source-confirmed inconsistency, medium priority.** [App's focus trap](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/App.tsx#L303) selects the first role=dialog in DOM order and depends on a manually maintained list of App states. [Visibility booleans](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/App.tsx#L668) can coexist. Export uses native [dialog](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/Viewer.tsx#L367); the [installing dialog](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/updates.tsx#L91) can lack a focusable child.

Introduce one primitive/stack with active modal, initial focus, background inertness, Escape policy, busy semantics and focus return. Native HTML dialog is a candidate after actual WebView checks. Use a focusable heading/container when no controls exist. Standardize workspace/tab navigation semantics.

Acceptance: keyboard-only minimum-size/200%-text workflows; theme contrast/focus checks; reduced motion; actual screen-reader checks on supported OSes. Automated accessibility checks complement, not replace, assistive technology.

### UI-11 Declare tool semantics for current callers

**Source-confirmed duplication, medium priority.** [Canvas before/after](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/store.ts#L63) scans parameter values; [coordinate reference](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/ToolForm.tsx#L382) uses a first-image heuristic and paste special case; [pin groups](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/components/Timeline.tsx#L219) hardcode field names. CLI serialization adds another interpretation.

Declare primary input, coordinate-space reference, lock category, and argv semantics in registry metadata only where current consumers need them. Keep core validation authoritative. Acceptance: a tool using existing semantic types does not need unrelated viewer/form/pin/CLI patches; multi-input before/coordinate behavior is explicit.

### UI-12 Preserve theme tokens and isolate feature styles

**Source-confirmed organization, medium priority.** [themes.css](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/themes.css) already provides useful material/color/font tokens and prohibits effects on artwork. [style.css](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src/style.css) mixes base controls, layout and feature rules alongside smaller stylesheets; Tailwind and plain CSS coexist.

Retain tokens and artwork isolation. Organize base controls/layout/feature styles; use CSS layers or modules where they prevent interference. Standardize spacing, typography, focus, target size and state tokens. Remove duplication as features move, without unrelated appearance changes. A new design-system package or total CSS rewrite is not justified.

Acceptance: themes do not alter image pixels/filter ancestors; contrast, focus, text scale and motion remain consistent; feature CSS cannot silently restyle unrelated controls.

### SH-01 Bound shell logs and diagnostic reads

**Source-confirmed resource issue, medium priority.** The [supervisor](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src-tauri/src/supervisor.rs#L124) rotates shell.log only before launch, then redirects stderr directly. [Diagnostics](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src-tauri/src/lib.rs#L76) reads the entire file before taking 200 lines.

A noisy long-running dependency can grow the file indefinitely and cause a large diagnostic allocation. Use a bounded rotating stderr sink and bounded-byte tail, correlate launch/operation IDs, preserve redaction and user review before sharing. No telemetry service is required.

Acceptance: synthetic stderr floods respect disk/memory bounds, pipes keep draining, diagnostics stays responsive.

### SH-02 Isolate the macOS lifecycle bridge

**Future compatibility risk, medium priority.** [macos_quit.rs](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src-tauri/src/macos_quit.rs#L42) adds applicationShouldTerminate: to Tao's delegate. A failed class_addMethod becomes an error propagated through [setup](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src-tauri/src/lib.rs#L170) into initialization failure. A future upstream implementation of that selector could break startup; this is not an observed current failure.

Document/version-test the assumptions, investigate supported hooks, and preserve Dock/menu/OS quit, close cancellation, update restart and cleanup. Prefer useful diagnostics over pre-UI abort where possible. Add actual Mac lifecycle tests to dependency update validation.

### SH-03 Bound updater storage

**Source-confirmed allocation, medium priority.** [Updates.pending](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src-tauri/src/updates.rs#L36) retains complete installer bytes in Vec; [download](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src-tauri/src/updates.rs#L142) completes before unsaved-work confirmation. Cancelling that later confirmation retains the bytes until another check/restart.

Measure RSS/retention per package. Investigate supported streaming-to-disk without bypassing signatures, disk admission, size bounds, cleanup and cancel-after-download policy. Preserve explicit install consent and core policy leases. Acceptance: interruption/retry/cancel/failed installer/success/rollback have bounded resources and correct recovery.

### SH-04 Verify the whole native process tree

**Investigation, not a confirmed orphan defect.** [Unix launch](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/src-tauri/src/supervisor.rs#L145) uses process groups; Windows only CREATE_NO_WINDOW at the shell boundary. Python workers/CLIs have separate ownership and parent-watch mechanisms; core stdin EOF shutdown exists.

Map packaged and source uv-wrapper/core/worker/CLI/MCP/local-runtime ownership. Test shell/core/wrapper/worker failure, hung startup and shutdown on each OS. Add OS ownership primitives only for demonstrated gaps, proving nested Windows Job compatibility. State restart-budget/reset policy explicitly. Acceptance: all owned children stop within a bound; unrelated processes are untouched; restarts leave no old serving worker or held data lock.

### REL-01 Automate evidence without weakening candidate gates

**Source-confirmed coverage/cost, medium priority.** [Six-target acceptance](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/packaging/release_gate.py#L15) requires many manual checks. [Native CI](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/.github/workflows/native-desktop.yml#L156) exercises more native editing on Windows than Mac/Linux; [docs](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/docs/releasing.md#L398) accurately state remaining coverage. The gate validates identity/completeness/result/URL shape, while the reviewer assesses manual evidence quality.

Produce typed native receipts tied to source, package hash, platform, environment, test identity, result and retained artifacts. Automate repeated file/clipboard/update checks. Keep genuine manual OS-trust/clean-machine/assistive-technology checks. If capacity is insufficient, reduce cadence or package scope explicitly rather than weakening evidence.

Acceptance: rebuilt bytes require fresh acceptance; missing/skipped/failed checks remain incomplete; nightlies meet their stated standard; published assets remain immutable.

### REL-02 Plan file-access capabilities and OS trust

**Known choices, medium priority.** [Flatpak](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/packaging/flatpak.json) grants home/network access, honestly [documented](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/docs/releasing.md#L308). [OS signing/notarization](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/docs/releasing.md#L187) is deferred, separate from update signatures.

Design Rust/Python file grants before portal-only access: import lifetimes, exports, saved/reopened projects, collections and external CLI access. Decide whether a restrictive Flatpak is a supported product or another package is the full-function path. Plan identities, expiry/renewal, clean-download checks and recovery ownership for signing.

Acceptance: authorized files reopen without broad accidental access; unsupported host CLI behavior is explained; OS trust and updater integrity are independently verified; broad-home-access packaging is not marketed as a strict sandbox.

### REL-03 Measure frozen payload breadth

**Source-confirmed, medium priority.** The [PyInstaller spec](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/packaging/badshop-core.spec) broadly collects runtime packages/provider adapters and distribution metadata. The [SBOM policy](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/docs/releasing.md#L201) deliberately includes build/non-host dependencies.

Profile import traces, frozen cold start, installed size and supported feature reachability. Distinguish observed installed inventory from inclusive SBOM without claiming static reachability completeness. Prune only after frozen feature tests, retaining dynamic adapters/keyring and legal notices. Optional payloads are worthwhile only if savings justify another signed distribution/update lifecycle.

Acceptance: every supported capability passes in the reduced frozen build; lazy imports remain lazy; missing adapters fail clearly; actual size/startup gains and inventory completeness are retained.

### VER-01 Measure runtime and native behavior

**Coverage boundary, medium priority.** [resource_report.py](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/scripts/resource_report.py#L17) counts build/package bytes; [frontend CI](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/.github/workflows/frontend-checks.yml#L25) gives no comparison baseline. No long-history UI latency/memory benchmark or automated accessibility checker was found. [Playwright](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/app/playwright.config.ts) defaults to Chromium, not native Tauri WebViews.

Add representative normal/stress workloads and a platform-risk matrix. Measure time to usable renderer, p95 input/stream/artifact-switch latency, save/reopen/reconnect, JS heap/RSS, transfer bytes and request counts. Use stable-hardware trend gates with tolerances and fixed safety bounds where justified. Add accessibility checks to primary journeys plus actual assistive-technology checks. Continue focused test selection, not blanket full-suite runs.

Acceptance: evidence identifies source/locks/hardware/renderer/workload and skipped/failed checks. Bundle size is not reported as UI responsiveness; a browser pass is not native-dialog evidence.

## Target architecture

| Owner | Responsibilities | Exclusions |
| --- | --- | --- |
| Protocol | Versioned schemas, errors, actor capabilities, generated types | Rendering/storage implementation or another domain engine |
| Connection runtime | Authentication, generations, correlation, deadlines/cancellation, uncertain outcomes, reconnect | Pixel algorithms or persisted project semantics |
| Document projection | Identity/revision-aware entities, indexes, deltas and resync | Authoritative mutation and image bytes |
| Live operation state | Streams, progress, requests, approvals, connection health | Persisted transcript or duplicate step truth |
| Media cache | Hash-addressed representations, Blob lifetimes, byte budgets, cancellation | Artifact authority or arbitrary paths |
| Features | Drafts, navigation, presentation, command intent | Engine invocation or independent policy |
| Native bridge | OS integration, process ownership, install, bounded diagnostics | Another settings authority or pixel path |
| Release evidence | Exact receipts, provenance, integrity, platform acceptance | Treating missing verification as success |

A possible organization is protocol/, runtime/, document/, media/, and features/{chat,timeline,viewer,materials,creative,settings}. Move responsibility while moving code. Do not add forwarding layers that leave the original state owner intact.

## Migration sequence

1. **Establish invariants and baselines.** Inventory public methods/events and consumers; preserve save/recovery/approval behavior with focused tests. Measure empty, 30–100-step normal, 1,000-step stress, many-branch, large-library and animation workloads on WebKitGTK/WebView2/WKWebView. Treat larger loads as exploratory stress until product targets are chosen. Reproduce identity races before claiming a current defect.
2. **Generate contracts and identity.** Add document/branch/operation/event identity and revision-aware reconciliation. Separate streams from document cache; introduce selectors and explicit query effects. Remove superseded reducers/invalidation as each consumer migrates. Compatibility code must name an actual supported version and removal condition.
3. **Bound media and rendering.** Benchmark transport alternatives; introduce byte budgets and representation cleanup; window lists without breaking focus/scroll; separate static/live Markdown. Repeat identical measurements before claiming gains.
4. **Refactor feature/modal ownership.** Extract App lifecycles, explicit drafts, recovery boundaries, consistent dialogs and current-needed tool metadata. Add shell-specific argv formatting. Code-split secondary panels and move CSS by ownership while preserving appearance/pixels.
5. **Strengthen native/delivery operations.** Bound logs and updater resources, test whole-process ownership, isolate Mac bridge assumptions, automate acceptance receipts, evaluate portal access/signing, and reduce frozen payloads only with runtime evidence.

Each phase consists of narrow behavior-specific or behavior-preserving PRs. Remove replaced paths rather than accumulating compatibility wrappers. Existing correctness and release guards remain active throughout migration.

## Acceptance matrix

| Action/interruption | Visible result | Persistence, error and cleanup |
| --- | --- | --- |
| Stream in a long project | Typing/scrolling/image selection remain responsive | No full snapshot per token; bounded buffering; completed reply appears once |
| Replace while old event is delayed | Only replacement document shown | Foreign/old events rejected; no reused-step-ID contamination |
| Disconnect during mutation | Outcome certainty is clear | No duplicate automatic side effect; reconnect reconciles operation/document |
| Browse many images/frames | Progressive useful previews | Bounded cache/RSS; stale requests curtailed; source bytes retained |
| Open/traverse/close dialogs | Focus remains active and returns correctly | Background inert; explicit Escape/busy policy |
| Trigger render exception | Recovery/diagnostics available | Core not silently destroyed; saved/recoverable work retained |
| Copy punctuated CLI command | Correct selected-shell command | Actual argv roundtrip; input exports have expected bytes |
| Flood stderr | App remains responsive | Bounded disk and diagnostic read; pipes keep draining |
| Kill owned process | Clear recovery or clean exit | All owned children stop within bound; unrelated processes untouched |
| Cancel downloaded update | Coherent UI | Bytes/files released or explicitly bounded retention |
| Upgrade exact signed candidate | Expected project/pixels reopen | Tamper rejection, old-process cleanup, compatible rollback |
| Change theme/scale/motion | Readable usable controls | Artwork pixels untouched; motion honored; preference failure safe |

## Technology alternatives

Retain Tauri unless measured WebKit-specific failures dominate support cost. Electron could reduce renderer variation but adds Chromium distribution, patching, package/RAM/startup costs. It still requires native dialogs/keychain/process/update/installer tests. A representative comparative prototype is appropriate only with explicit success criteria; this source audit does not establish its outcome.

Retain Python pixels: Rust would not solve event identity, JSON churn, eager history, or renderer recovery. Consider isolated native acceleration only for a measured bottleneck, with a narrow interface and golden parity. Retain React and useful state libraries; improve ownership rather than recreating authoritative Session logic in another frontend store.

Do not turn coordinate correction into an unplanned scene-graph editor. It remains parameter entry over recorded deterministic operations. Do not introduce a general plugin system without a present requirement: it adds capability, isolation, dependency, compatibility, signing and support obligations. Keep theme tokens; do not rebuild styling solely for uniformity.

Make release evidence cheaper to produce rather than weaker. A sustainable platform matrix is better than promising unverified packages. No new telemetry service is necessary for this plan.

## Coverage and uncertainty

This appendix covers protocol consumption, frontend state/render/media ownership, schema forms, tool semantics, workflow composition, themes/CSS, modal/accessibility behavior, renderer recovery, native supervision/integration, updater policy/storage, packaging dependencies, release integrity, and verification/maintenance. Companion audits cover authoritative session/persistence/engine/provider behavior.

Source confirms structural scaling costs and ownership limitations; it does not establish their frequency or measured latency. No release artifact, native trust state, live repository protection, screen reader or alternative framework was executed. The PowerShell probe establishes command parse failure only. These limits define the first validation steps without weakening the evidence-backed architectural recommendations.
