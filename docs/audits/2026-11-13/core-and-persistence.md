# Core execution and persistence audit

Audit baseline: `fb1ad675546bd466d5578fbf324a72361458a619`, 13 November 2026. This appendix covers Python session, artifact, execution, worker, project, branch, library, recipe, remix and media ownership. All source links are pinned to that revision. The recommendations are proposals, not changes to current product contracts.

The Python architecture is worth retaining. The largest long-term problems are the document model's conflation of blob identity with editing identity, full-history branch copying, in-memory storage and full-archive autosaves, and implicit ownership of infrastructure. These are better targets than rewriting the pixel engine.

Two defects were confirmed through standard-library probes executing unchanged production method bodies with fake collaborators. These are source-logic and fault-injection checks, **not application integration tests**. They do not import BadShop, Pillow or Pydantic. No application source was modified. The global Python environment inspected for this audit lacks those dependencies, and the isolated audit checkout had no virtualenv. The probes and JSON output are retained under `artifacts/verification/architecture-audit/` with the final audit evidence.

## Immediate defects

### C1 Opening a branched project disables its bounded decoder

**Status: confirmed code defect; constructor side effect reproduced with a source-body probe. Priority: high.**

The desktop supplies its decoder worker through [`CoreApp._session_kw`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/app.py#L241). Project loading creates an artifact store and the live session with that decoder, then validates each branch by constructing `Session(branch_data, artifacts)` against the **same artifact store**, omitting the decoder. See [`project.open_project`, lines 430–454](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/project.py#L430).

[`Session.__init__`, lines 133–137](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/session.py#L133) unconditionally assigns `self.artifacts.decoder = decoder`, whose default is `None`. [`ArtifactStore._open`, lines 98–101](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/artifacts.py#L98) consequently falls back to in-process decoding.

The triggering workflow is ordinary: save and reopen a project containing directions or AI-turn checkpoints, then request a thumbnail or import another picture. Initial archive validation uses the injected worker, but subsequent reads and imports lose that resource/crash boundary. This is not a claim that a particular malicious image was executed.

The probe compiles the unchanged constructor body, constructs a session with a decoder spy, then constructs a validation session with the same store and default arguments:

```text
before branch validation, injected decoder retained: True
after branch validation, injected decoder retained: False
after branch validation, decoder is None: True
```

**Repair:** the artifact store should own its injected decoder for its lifetime. A pure branch-reference validator should inspect model data without constructing a behavioral session. Merely passing another keyword at this one call site leaves the ownership trap available elsewhere.

**Acceptance:** save/reopen both branched and unbranched projects; confirm decoder identity remains unchanged; exercise a real thumbnail request and subsequent import with the worker. Validation must not mutate infrastructure or start execution. Keep a focused constructor/validator regression alongside the actual open-project workflow.

### C2 Failed exports leave partial final-name files

**Status: confirmed code defect; partial-write failure reproduced with a source-body probe. Priority: medium.**

[`Session.export`, lines 431–458](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/session.py#L431) chooses a new filename, opens it with `xb` and writes directly to it. It translates `OSError` without removing the partially written file.

If the disk fills after some bytes are written, or the core is killed during a large export, a visibly named `result.png` can remain despite the operation failing. Existing never-overwrite protection is good; atomic completion is missing.

The probe executes the unchanged export body using a real temporary directory, fake artifact bytes and an injected writer that writes four bytes before raising `OSError`. The translated error occurs, but the final filename remains:

```text
final-name export survives failed write: True
leftover fake bytes: b'comp'
```

**Repair:** create an explicit primitive for publishing a complete new file without replacing another owner's file. Stage bytes in the destination directory, synchronize them where the durability contract requires it, publish with a platform-appropriate non-overwriting operation, and clean incomplete owned files on handled failure. Ordinary `os.replace` onto a previously selected filename would weaken the existing race guarantee and is not a sufficient replacement.

**Acceptance:** inject partial write, close and publication failures; race another process for the final name; exercise cancellation and process interruption. Existing user files remain unchanged. Handled failures leave no partial final-name export. A killed writer may leave an owned staging file, which cleanup can safely identify.

### C3 Same-version nightlies can reuse results from changed engine code

**Status: confirmed cache-key omission; cross-build output reuse is a concrete reachable scenario, not a newly run installer test. Priority: high-value correctness work.**

[`execution.cache_key`, lines 197–203](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/execution.py#L197) hashes application `__version__`, runtime/library/codec versions, tool name and parameters. The core version is [`0.4.3`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/__init__.py#L3). The nightly workflow rewrites only the Tauri configuration's version in [`native-desktop.yml`, lines 119–128](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/.github/workflows/native-desktop.yml#L119).

Two nightlies with different engine code but the same core version and dependencies can therefore share cache keys. Opening a project from the earlier nightly and using normal replay may reuse old results instead of executing the changed implementation.

**Repair:** distinguish preserved display pixels from execution semantics. Opening must retain the saved bytes. An explicit replay should apply the chosen semantics and invalidate caches correctly. Add immutable build identity first, then deliberate semantic versions per tool when that granularity is useful. Do not invalidate every image result for an unrelated frontend edit once tool-specific semantics are available.

**Acceptance:** a changed execution fingerprint forces a real run; unchanged semantics reuse results; opening alone does not rewrite saved pixels; nightly build metadata identifies the actual core implementation, not only the shell package.

### C4 Resolved external assets are absent from execution identity

**Status: confirmed omission; visible impact depends on changed fonts/resources. Priority: medium.**

The [runtime fingerprint](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/execution.py#L184) excludes resolved fonts and model bytes. [Font lookup](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/engine/text.py#L59) resolves system or custom files by path/name and caches the path. [Background removal](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/engine/cutout.py#L26) reuses a session backed by model assets.

Replacing a custom font, installing a different font with the same filename or moving a project to another machine can make a cache hit and a forced replay disagree despite identical apparent parameters. The current document cannot fully explain that difference. Downloaded model/font pinning in the [asset manifest](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/engine/manifest.py#L39) is a useful foundation.

**Repair:** record resolved asset digests and renderer semantics per invocation. For system/custom fonts, offer a defined project-resource strategy or explicitly report a missing/mismatched resource. Embedding fonts must respect redistribution rights. Silent fallback to another font is incompatible with a strong reproducibility promise.

## Structural findings

### C5 Blob identity is being used as editing and provenance identity

**Status: intentional current design with increasing architectural cost.**

[`ArtifactMeta`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/models.py#L30) explicitly retains the first label and producer for equal bytes. [`ArtifactStore.add`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/artifacts.py#L134) returns existing metadata unchanged when a content hash already exists. Replay compensates with a [producer-sensitive remapping table](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/session.py#L68).

Several features independently reconstruct ancestry:

- [`recipes.credits`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/recipes.py#L84) matches both step IDs and output membership across branches.
- [`Session._stem`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/session.py#L179) follows metadata's first producer.
- [`AssetLibrary.save`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/library.py#L106) selects a preferred lineage using `piece` or the first input.
- [`remix.dependencies`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/remix.py#L15) scans backward for a matching output producer.

This is not an accidental deduplication defect: [replay tests](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/tests/test_replay.py#L391) establish the current first-producer metadata/latest-preceding-producer semantics. Changing it requires a deliberate migration.

The consequence is that two acquisitions of identical bytes can retain only the first source attribution, and equal-byte outputs cannot unambiguously identify separate logical edges. Provenance and replay answer related questions using different rules. This becomes more costly as branches, sharing, reusable characters and recipes expand.

**Target:** retain byte deduplication but separate `Blob`, `ArtifactUse`, `Invocation`, named `OutputPort`, `InputBinding` and `SourceEvidence`. One blob can support many independently attributed uses. Engine functions still receive images and return results; the adaptation belongs at the session boundary.

### C6 Replay discards output keys and remaps by list position

[`OutputRecord`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/execution.py#L58) has a stable `key`, but [`Step.outputs`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/models.py#L55) persists only blob IDs in a list. [`_advance`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/session.py#L68) maps old position `i` to new position `i`; when there are fewer new outputs, an unmatched old reference is retained.

A downstream operation can continue consuming an old image when its producing operation no longer emits that output. Reordered multi-output results can redirect dependencies. These are consequences of the current code, not newly exercised UI regressions.

Persist named output ports. A missing port should produce an explicit disconnected/dependency error. A user can deliberately freeze an old result, but that should be a recorded choice. Verify fewer outputs, reordered outputs, equal-byte ports, bypass, rejected steps and interrupted replay.

### C7 AI checkpoints copy whole histories twice per turn

[`branches._snapshot`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/branches.py#L15) deep-copies steps, messages and transcript. [`begin_turn`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/branches.py#L121) creates two branches per turn without pruning prior automatic checkpoints. The document stores active history as well as branch snapshots, and [`MAX_SESSION_BYTES`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/project.py#L47) limits metadata to 16 MiB.

For histories that grow with every turn, copied metadata grows approximately with the sum of prior history lengths: quadratic growth. Images are shared, which helps, but the repeated text and step records can still make a long project unsavable.

Use immutable revisions/shared invocation records and branch heads. Retain named user branches. Give automatic undo checkpoints an explicit bounded retention policy and an option to promote a checkpoint. Never silently delete user-created directions. Acceptance should include thousands of small operations with near-linear metadata growth, plus undo/branch/save/open behavior.

### C8 All encoded project images remain in core memory

[`ArtifactStore`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/artifacts.py#L90) stores every encoded blob in a dictionary. Its 2 GiB capacity check repeatedly sums retained lengths. Successful replay adds new output bytes without collecting obsolete results. [`delete_last`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/session.py#L665) deliberately preserves images. Production `drop` calls only implement rollback. Project save filters reachable artifacts but does not compact the live store.

Therefore a long running session can consume more memory than its saved/reopened equivalent. The encoded-byte cap is not a bound on process memory: decoded images, worker transport, JSON and frontend representations also contribute. The capacity error suggests removing unused images, although the inspected RPC surface has no artifact-delete operation.

Use disk-backed content-addressed blobs and bounded decoded/thumbnail caches. Define reachability across active revisions, branches, chat attachments, library assets, undo checkpoints and in-flight jobs. Garbage collection must respect leases; a blob absent from the active timeline may still be required elsewhere. Introduce storage inspection or explicit compaction before automatic pruning.

### C9 Autosave rewrites the archive under the document lock

[`CoreApp._blocking`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/app.py#L311) holds the global document lock while running a mutation and its autosave. [`project.save`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/project.py#L147) serializes all metadata, derives a CLI recipe, writes every retained blob and fsyncs the file.

This prioritizes correctness over throughput and avoids unsynchronized saves. Its cost nevertheless scales with the whole project even for small metadata changes. The audit did not measure latency on large projects; the structural cost follows directly from the write path.

A plausible target is transactional local metadata, such as SQLite after a bounded prototype, plus immutable disk blobs. Commit each completed operation and its revision atomically; publish the durable state afterward. Recovery opens the latest committed revision. Explicit Save/Save As exports a consistent revision snapshot to a portable archive without holding the mutation lock during all blob copying. Its result must identify the saved revision so newer edits remain dirty.

An operation journal may aid recovery and diagnostics, but it must belong to the same commit boundary. Do not introduce an independent event log and database that both claim authority. Full event sourcing is not required by this recommendation.

### C10 Validation creates mutable runtime objects

The decoder defect demonstrates a broader boundary problem: [`open_project`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/project.py#L448) constructs temporary sessions to collect references, while the constructor configures infrastructure and aliases metadata dictionaries.

Use pure validation/reference-traversal functions over model data and a read-only artifact index. Return validated data and diagnostics. Construct the live session exactly once after validation succeeds. This also makes archive fuzzing easier and reduces hidden setup side effects.

### C11 Ordinary saving depends on CLI syntax generation

[`project.export_recipe`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/project.py#L96) converts stored invocations through CLI `to_argv`; [every save invokes it](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/project.py#L153). A CLI representation failure can block saving an otherwise valid document.

Store canonical invocations as document data. Make CLI recipes explicit derived exports or a nonessential compatibility member with a versioned contract. Keep promised readers while their compatibility window exists, but do not make a future document schema subordinate to argparse syntax.

### C12 Effective tool policy is distributed across layers

The [registry](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/tools/registry.py#L14) has useful capability flags. However, [`Session.propose`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/session.py#L277) hardcodes defaults for particular tools, bypass uses a separate whitelist, and [`CoreApp._own`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/server/app.py#L260) dynamically adds session policy attributes.

Keep a single validated invocation path, but make its inputs explicit: typed policy/context, canonical effective parameters, named outputs and optional bypass capability. These current callers justify the boundary. They do not justify a general plugin framework or workflow language merely to move a few conditionals.

### C13 Library persistence lacks a complete storage lifecycle

The [library installation path](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/library.py#L153) validates a batch before publication and removes new entries on handled failures. Hash checking and independent atomic entry records are strengths.

Limitations remain:

- [`remove`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/library.py#L208) keeps shared blobs indefinitely, with no collection path.
- [`list`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/library.py#L64) loads every JSON record and propagates the first corrupt-record error.
- [Blob publication](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/library.py#L191) does not fsync bytes, while metadata records do. Process-crash atomic replacement is not equivalent to power-loss durability.
- [Thumbnail requests](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/library.py#L251) decode images again; search scans all JSON records.

Add reference accounting, indexed/paginated queries and cached derivatives. Surface corrupt records as repairable/quarantined entries instead of making the whole library unavailable. Document the durability target and verify it at its actual layer; this audit does not establish physical power-loss behavior.

### C14 Resource accounting stops short of transport and total memory

**Status: confirmed boundary characteristics; severity and practical limits require measurement/fault injection.**

The [worker](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/worker.py#L75) already provides spawn isolation, cancellation, restart, RSS monitoring, child cleanup and a core-death sentinel. Preserve that work.

Calls and decode results carry entire encoded images or raw pixel buffers. [`conn.send`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/worker.py#L150) is synchronous before the receive watchdog. [`_receive`](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/worker.py#L195) performs synchronous `recv` after `poll`, then checks cancellation/time/RSS. The RSS budget covers worker descendants, not all core/renderer copies. Download progress extends deadlines, which is useful but calls for an independent transfer budget.

Profile large valid inputs and inject partial/slow IPC before replacing transport. Consider bounded metadata plus strictly validated blob handles/paths and explicit leases instead of repeatedly pickling large buffers. This is resource/crash isolation, not an OS sandbox against a compromised decoder.

## Architecture to retain

1. **One application tool-execution path.** Manual actions, model calls and subscription CLI requests reach the session. The standalone parity CLI's direct runner path is a documented exception. [Import contracts](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/.importlinter) and Ruff restrictions enforce useful boundaries.
2. **The existing pixel engine.** Preserve reference-compatible output and local seeded randomness. Architectural modernization must not silently change the intended aesthetic or introduce image generation.
3. **Content hashing and preserved originals.** These are valuable; separate logical editing identity around them rather than replacing deduplication.
4. **Supervised workers.** Repair decoder ownership and strengthen limits instead of moving expensive native libraries back into the core.
5. **Archive defenses.** [Directory/member/size checks, bounded reads, hashes and transcript sanitization](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/project.py#L199) provide meaningful protection.
6. **Interrupted-operation recovery.** [Unapproved work is rejected and approved/running work becomes failed](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/project.py#L380). Migration must never execute historical proposals automatically.
7. **Frozen local-media evidence.** [Media imports](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/media.py#L202) record selection/crop/frame facts; [collection imports](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/local_collection.py#L136) recheck source hashes and paths.
8. **Meaningful behavioral tests.** Existing replay, historical-project, archive, branch and byte-output tests should become migration acceptance cases, not be replaced by tests of mocked call counts.

## Proposed document model

This is a target model to validate with a prototype, not a mandate to add all entities at once.

| Entity | Identity and important fields | Ownership rule |
| --- | --- | --- |
| Blob | SHA-256; size; media format; dimensions/frame metadata; storage location | Immutable bytes; multiple logical uses can share it |
| ArtifactUse | Stable ID; blob ID; source evidence; original/working relationship | An import or produced logical picture has identity independent of bytes |
| Invocation | Stable ID; tool ID; semantic version; effective parameters; actor; approval decision; status | One operation proposal and its result belong to the document owner |
| OutputPort | Invocation ID; stable named port; artifact-use ID | Consumers bind to a declared output, not a position inferred later |
| InputBinding | Parameter/port; imported-use or prior-output reference; optional explicit frozen revision | Replay can distinguish follow-output from keep-these-bytes |
| Revision | Stable ID; parent revision; operation/change set; branch membership | Immutable committed document state or reconstructible persistent structure |
| Branch | Stable ID; name; head revision; user/automatic kind | User branches persist; automatic retention follows an explicit policy |
| SourceEvidence | Source URL/page/creator/license; original hash; crop/page/time facts; retrieval evidence | Evidence can be multiple-valued and does not claim rights verification |
| ExecutionManifest | Core build; tool semantic version; dependency/codec fingerprint; resolved asset digests | Explains whether replay is compatible and why cache entries differ |

Use JSON-compatible canonical parameter values and generate protocol types from authoritative schemas. Do not put Python pickle objects or live provider SDK structures in the portable format. Keep provider conversation state explicitly separate from the domain graph and classify it as untrusted imported data.

Do not promise global exactly-once execution. The practical contract is one committed result for a document operation identity, with retry/idempotency rules at the boundary. External effects such as export and remote requests require their own reconciliation; a local transaction cannot roll them back.

## Migration and acceptance sequence

### 1 Repair defects before changing the data model

Deliver C1 decoder ownership, C2 export publication and C3 execution fingerprint as separately reviewable behavior changes. Retain focused regressions and a real open/branch/save/reopen/import workflow. Fixes should not depend on completing the larger migration.

### 2 Define invariants and extract pure validation

Write invariants for stable invocation identity, named outputs, approvals, revisions, blob ownership and missing dependencies. Extract reference traversal/validation without changing serialized semantics. Record schema 1–4 behavior, including intentional first-producer/latest-preceding-producer rules and any ambiguity that old documents cannot resolve.

### 3 Introduce explicit output references in a new schema

Read old documents without changing saved pixels. Infer legacy consumer bindings using the existing replay rules so playback meaning is preserved. Where equal-byte histories lack enough information to identify the user's intended logical source, record that limitation instead of inventing provenance. Keep `s1` labels for display while using stable internal IDs.

Migration cases must include bypass; repeated equal outputs; removed outputs; branches whose step IDs repeat across directions; deleted-step chat attachments; interrupted replay; original/working-copy links; unknown tools; and incompatible resource manifests. Verify all referenced blobs by hash. Write a new copy and retain the original archive. Do not overwrite the only old-format file during upgrade.

### 4 Replace copied checkpoints with shared revisions

Preserve named directions and current undo semantics. Bound automatic checkpoints explicitly and allow promotion to named branches. Verify near-linear metadata growth on long histories, deterministic branch activation, unchanged saved pixels and proper provider-context invalidation. A full generic DAG editor is unnecessary; the UI may remain a linear timeline over a graph-aware internal model.

### 5 Introduce transactional metadata and disk blobs

Prototype a local store on representative 1,000-step, 100-turn and image-heavy projects. Publish complete immutable blobs before committing their references. An interrupted operation may leave collectible orphan blobs; it must not leave a committed document pointing to unavailable bytes. Define leases for exports and running workers so collection cannot race them.

Archive import validates into staging and only then activates a document. Archive export reads a stable revision. The save acknowledgment identifies that revision, while later edits stay unsaved. Journaling, database state and notifications must have one authority and an explicit commit order. This is a single-user desktop store; distributed coordination is not required.

Retain schema 1–4 readers and fixtures through the stated compatibility window. Avoid indefinite dual writes to old and new stores. Define the cutover and removal condition before implementation. Power-loss durability must be described separately from atomic replacement and process-crash recovery, including platform-specific synchronization choices.

### 6 Establish storage lifecycle and performance budgets

Measure cold/warm import, thumbnail latency, tool time, replay time, save/open latency, retained memory, disk growth and shutdown. Use measurements to set budgets. Add safe compaction and corruption repair. Keep imports, library assets, branches, attachments and in-flight leases in reachability accounting. Report reclaimed versus retained bytes so behavior is inspectable.

### 7 Stabilize cross-version execution

Record tool semantic versions, build identity and asset digests. Distinguish displaying saved pixels, replaying with compatible resources, upgrading an operation and refreshing a remote source. Prefer inspection/export access for documents with an unsupported tool; editing that operation can be unavailable. The current loader [rejects unknown tools or invalid current parameters](https://github.com/dan-wiseman94/BadShop/blob/fb1ad675546bd466d5578fbf324a72361458a619/core/src/badshop/session/project.py#L341), so this is an explicit product/compatibility change requiring tests and UI explanation.

### 8 Verify contracts at the affected boundary

Build on `test_session.py`, `test_artifacts.py`, `test_replay.py`, `test_project.py`, `test_project_boundaries.py`, `test_project_compatibility.py`, `test_library_branches.py`, `test_recipes.py`, `test_local_media.py`, `test_worker.py` and `test_golden.py` under `core/tests/`.

Add property/state-machine cases for import → execute → edit → replay → branch → undo → save/open. Invariants include: committed references resolve; unapproved operations do not execute; equal blobs can retain distinct logical provenance; output bindings remain stable; save/open preserves visible bytes; interrupted commits recover to a coherent revision.

Use focused Linux worker/project tests in the isolated private WSL worktree and one actual browser/core journey for cross-boundary changes. Use native/installer verification when process or packaging boundaries change. A source-body probe, browser test and installed-platform workflow establish different things and must remain labeled separately.

The recommended direction is a versioned document graph over content-addressed blobs, one transactional operation owner and bounded execution workers. It preserves BadShop's strong foundations while replacing inference from content hashes, copied histories and mutable shared objects with explicit relationships.
