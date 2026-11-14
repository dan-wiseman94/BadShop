# BadShop architecture modernization plan

**Status:** proposed implementation plan, not implemented behavior. **Baseline:** `fb1ad675546bd466d5578fbf324a72361458a619`. Read the [architecture audit](../../architecture-audit-2026-11-13.md) and its three subsystem appendices for findings and pinned code evidence.

The objective is to make BadShop reliable and understandable as a local creative workshop: import images, make deterministic edits manually or through an agent, revise individual choices, keep alternate takes, reuse material, share a finished image or editable remix, and return later without losing work. The engine remains the sole pixel producer. Projects must remain usable independently of a particular AI provider or conversation format.

The recommended change is substantial inside the core: a versioned document graph with stable logical image/output identities, a single operation owner, and transactional workspace storage over immutable disk blobs. React and Tauri remain. Migration proceeds through small observable changes and releases; old and new live persistence must not become permanent parallel implementations.

## Governing invariants

1. A committed document reference resolves to complete, verified, durable image bytes. A failed operation can leave an unreferenced staging blob, but cannot commit a reference to missing bytes.
2. Every command, approval, worker result, provider callback and event belongs to a specific core instance, document incarnation and operation. Reopening the same document ID creates a new incarnation.
3. The document has one commit owner. Expensive execution can happen outside its critical section; ownership and expected revision are checked again before publication.
4. API agents, external agents, recipes and manual actions use one validated invocation/policy path. Manual invocation is explicit user authorization, not a reason to skip validation or resource admission.
5. Opening old work never executes historical tools. Saved outputs remain visible even when replay resources are missing, where the file is structurally valid and safely inspectable.
6. Blob identity means encoded bytes. Artifact-use identity means a logical input/output with provenance. Invocation identity and named output ports determine dependencies. Display labels such as `s1` are not authority or identity.
7. Preview is a bounded, cancellable derived operation. It does not mutate the document, bypass import restrictions, or silently become a second rendering implementation.
8. A reported terminal outcome is durable and unambiguous where the program can know it. External side effects interrupted at an unknown point are reported as outcome-unknown and reconciled; the design does not claim universal exactly-once execution.
9. Permissions, Local only policy and resource budgets are enforced in the core. UI affordances and provider prompts are not enforcement boundaries.
10. Every retained cache, temporary file, image representation, provider process and checkpoint has an owner, retention rule and cleanup path.
11. New infrastructure preserves the deterministic engine's existing aesthetic and tested output behavior. Pixel changes require separate explicit product changes and golden review.
12. A migration leaves the original project usable. An application rollback never writes an older schema over newer work without a supported conversion.

## Delivery structure and sequencing

The work packages below describe coherent outcomes, not a requirement for one enormous PR per package. Each should be split into reviewable changes with one observable behavior change and removal of the replaced path. The estimates are rough planning ranges for focused engineering time, including tests and documentation, assuming familiarity with the code. They are not commitments and are not additive: prototypes, overlap and platform access will change them. The complete program is plausibly several months of one maintainer's work.

| Package | Outcome | Depends on | Initial size |
| --- | --- | --- | --- |
| W0 | Characterization, workload fixtures and invariants | Audit | 3–7 days |
| W1 | Immediate correctness/resource repairs | Can begin immediately | 4–10 days across independent PRs |
| W2 | Complete typed, revision-aware protocol | W0 | 1–3 weeks |
| W3 | Unified run and invocation ownership | W0, W2 identity contract | 2–4 weeks |
| W4 | Explicit document, artifact and output identities | W0, W2 | 2–4 weeks |
| W5 | Shared revisions and bounded automatic checkpoints | W4 | 1–3 weeks |
| W6 | Transactional metadata and immutable disk storage | W4, W5 prototype | 3–6 weeks |
| W7 | Resource-aware workers, previews and media transport | W2, W4; W6 for disk handles | 1–3 weeks |
| W8 | Normalized frontend projection and bounded rendering | W2; W4 for final graph views | 2–4 weeks |
| W9 | Provider-neutral context, budgets and compatibility | W3; W4 for typed history migration | 2–4 weeks |
| W10 | Coherent feature/UI ownership and accessibility | W8; independent small repairs earlier | 2–4 weeks |
| W11 | Library, source, recipe and remix lifecycle | W4, W6 | 1–3 weeks |
| W12 | Native lifecycle, update and installed-platform hardening | Independent; W2 for diagnostics | 1–3 weeks plus platform access |
| W13 | Release automation, dependencies and maintenance contracts | W0; repeated throughout | 1–3 weeks |
| W14 | Compatibility rollout, deletion and product validation | All applicable packages | 1–3 weeks plus beta observation |

The critical path is W0 → W2/W4 → W5/W6 → W14. Run W1 immediately. W3 and W9 can proceed in parallel with the document work once shared identities are agreed. UI work should consume stable contracts, not chase an evolving database layout. W12/W13 can ship incremental improvements independently.

Use four release checkpoints: repaired baseline; typed protocol/run lifecycle; new document/storage format behind explicit migration; and optimized/polished default. Every checkpoint must leave a usable app. Do not delay a proven decoder/export fix until the entire redesign is ready.

## W0 Establish behavior and performance baselines

**Owners:** existing session/project tests, browser/core fixtures, verification scripts and development documentation. **Purpose:** prevent the migration from trading well-understood behavior for cleaner-looking code with weaker guarantees.

Create a short invariant ledger with one canonical owner for each rule: image identity, original/working-copy relationship, operation ordering, approval states, bypass, branch ancestry, retry, save revision, network policy, worker ownership and recovery. Link existing tests rather than cloning them. Record where current behavior is intentional even if the redesign changes it, especially first-producer metadata and positional replay outputs.

Build reproducible workload fixtures using rights-cleared or generated deterministic images. Include an empty project; a normal 30–100-step editing project; a 1,000-step long history; 100 agent turns/checkpoints; 500–2,000 library entries; duplicate-byte imports with different provenance; multi-output operations; animated images; many small artifacts; and a few large valid sources. A 10,000-step case is exploratory stress until product needs justify supporting it. Do not make the quick suite generate every large case repeatedly.

Measure cold/warm usable launch, import, preview, tool execution, replay, save/reopen, branch switching, reconnect, core recovery and shutdown. Record p50/p95 interaction latency, bytes transferred, request counts, Python/Rust/renderer/worker RSS, JS heap, cache bytes, archive size, metadata size and bytes written per edit. Distinguish native startup, model startup and optional model download. Bundle size alone does not establish runtime efficiency.

Use identical sources, lockfiles, build mode and hardware for comparisons. Report failures and rejected/unsupported workloads. Persist source fingerprints and raw measurements. Establish a normal supported workload on a lower-powered target machine, then set budgets; the suggested targets later in this plan are starting proposals.

**Acceptance:** every baseline is reproducible; existing save/open output bytes and current branch/retry semantics are documented; the normal editing journey is measured in real UI/core and at least the primary native target. No application rewrite is needed to finish this package.

**Removal/avoidance:** do not create a second test harness, synthetic performance score or mirrored implementation tests. Extend current scripts and fixtures. Documentation-only portions need no app suite; new measurement helpers need their own focused checks.

## W1 Repair concrete defects before architectural migration

Each item is an independent small change, with a failing focused regression followed by the fix.

| Repair | Existing owner | Required behavior and distinguishing test |
| --- | --- | --- |
| Decoder lifetime | `ArtifactStore`, `Session.__init__`, project branch validation | Store retains its injected decoder after unbranched/branched reopen; actual thumbnail and subsequent import use the bounded decoder. Validation has no service mutation. |
| Atomic new-file export | `Session.export`, shared file helpers where appropriate | Disk-full/partial-write/close failure leaves no partial final-name image; concurrent claimant is never overwritten; existing files remain byte-identical. |
| Cache build identity | `execution.cache_key`, build/version generation | Two builds with changed engine semantics and equal dependency versions cannot accidentally share an execution cache key; opening still preserves old bytes. |
| CLI retirement | Core provider cache/lifecycle | Changing an idle persistent profile closes the superseded process and private directory; repeated changes do not accumulate retired instances. |
| Source health event | `data.ts` | An agent-completed source tool invalidates/reloads health through the actual `step.finished` event. |
| Shell-aware command copying | Timeline export and CLI serialization | Generated argv roundtrips spaces, apostrophes, quotes, backticks, dollar signs, newlines and Unicode in each advertised shell; the test must actually parse/receive argv, not compare a hand-written expected string. |
| Bounded shell diagnostics | Rust supervisor/log reader | Noisy stderr rotates during execution; diagnostics reads a bounded byte tail of a huge file. |

For export, preserve the existing exclusive/no-overwrite guarantee. Blindly replacing the final path with `os.replace` after checking that it is free introduces a race. Stage in the destination directory and use a platform-tested non-replacing publication primitive. Handle owned temporary-file cleanup separately from another process's file. If power-loss durability is promised, specify the file/directory flush contract and test what can actually be simulated.

Do not present the audit's extracted-method probes as the final regressions. Add real object/workflow tests in the isolated Python environment. Decoder repair crosses the desktop import/reopen boundary, so run one browser/core journey exercising it. Shell log changes warrant Rust plus relevant native lifecycle checks. Other repairs need only their focused selections.

**Acceptance:** regression fails for the original mechanism and passes with the repair; no pixel logic changes; documented error/recovery behavior is preserved. The repair release is useful even if the larger migration is postponed.

## W2 Make the complete protocol typed and revision aware

**Current owners:** `server/rpc.py`, `server/app.py`, feature registrars, `scripts/generate_wire_types.py`, `app/src/types.ts`, `rpc.ts`, `data.ts` and the updater's narrow Rust client.

Inventory all methods with their actor/capability, parameter model, result model, mutation/read classification, cancellation behavior, long-operation behavior and affected resources. The current dispatcher already derives parameter validation from Python signatures; retain that investment where it is clear. Add explicit result and event models. Generate TypeScript method/result maps and discriminated event unions from the same registered contracts. Generate the Rust subset actually used by the updater or validate it with a contract fixture; do not generate unused clients.

The handshake should identify protocol version, immutable build identity, core instance ID and capabilities. Bundled shell/core normally ship together, so mismatches can fail with an actionable message rather than building a permanent multi-version gateway. Independently installed MCP/headless clients need a stated minimum compatible protocol.

Document-scoped envelopes should contain:

| Field | Purpose |
| --- | --- |
| `core_instance_id` | Reject notifications from a prior core lifetime. |
| `document_id` | Stable identity of the creative document. |
| `document_incarnation` | Distinguish reopen/replacement of the same ID. |
| `branch_id` / revision context | Identify the timeline being read or changed. |
| `operation_id`, optional `run_id` | Correlate command, progress, approval and terminal outcome. |
| `event_seq` | Detect delivery gaps/order within a defined stream. |
| `revision` and optional `base_revision` | Prevent stale snapshots/deltas from replacing newer state. |

Keep global events such as download/update policy separate from document events, with their own owner and ordering. Do not attach meaningless document IDs to everything. Text/progress deltas may be ephemeral and coalesced; committed mutations must be recoverable by snapshot and operation lookup.

Give commands a caller request/idempotency identity where they can mutate. A lost response is not evidence that a mutation failed. On reconnect, query operation outcome or resynchronize before offering repeat. Never automatically replay all pending mutations when reconnecting.

Validate incoming replies/events at runtime, with strict size/depth constraints and useful diagnostics. A new event should fail compilation in exhaustive reducers or be deliberately handled as a known forward-compatible unknown. Replace arbitrary `Record<string, unknown>` casts with validated discriminants at the boundary.

Replace the generic internal-error assertion that the session is unaffected with a truthful outcome contract. A handler that has not committed can report no change; a known committed operation returns its receipt; an interrupted side effect can report outcome-unknown. The transport cannot promise rollback on behalf of every handler.

**Acceptance:** delay an old event until after new-project/open/branch-switch response; the old event is rejected even when both documents display `s1`. Deliver a stale snapshot after a newer delta; state does not regress. Drop a sequence number; client resynchronizes. Lose a mutation reply; no duplicate export occurs on automatic reconnect. Unknown protocol versions and malformed results fail clearly without losing recoverable work.

**Delete:** handwritten duplicate MethodMap/event names where generation replaces them, obsolete reconciliation branches and fake compatibility defaults. Keep a generated-file check in CI and a complete registered-method coverage contract.

## W3 Unify run lifecycle and tool invocation ownership

**Current owners:** `agent/loop.py`, `providers/cli_turn.py`, `CoreApp._cli_call/_run_or_reject`, `ApprovalGate`, recipe/batch orchestration and `Session` execution.

Introduce two concrete owners, with small typed interfaces:

- `RunController` owns run identity, initiating command, adapter instance, lifecycle, checkpoint reference, cancellation, deadlines, budgets, retry/continuation and terminal result.
- `InvocationService` owns effective parameter validation, input binding, policy, proposal, approval, resource admission, execution and settlement into the document.

These names are suggestions; their responsibilities matter. Do not put both in one generic framework or spread state across another set of private dictionaries. UI/manual operations can use the invocation service without pretending to be model turns. Recipe batches have a parent operation and sequential child invocations, not a second approval/execution engine.

Define lifecycle transitions explicitly. A run can be preparing, active, waiting for approval, cancelling, succeeded, failed, cancelled or outcome-unknown. An invocation can be proposed, awaiting approval, executing and terminal. Historical Step status compatibility can remain at the wire/view boundary during transition; avoid silently equating rejected, cancelled and failed.

Keep API and external-agent adapters distinct. A `CompletionAdapter` receives a typed projected context and returns a completion. An `ExternalAgentAdapter` owns a process/conversation and normalized stream, while tool execution returns through a scoped BadShop grant. An external agent should not fake the semantics of a stateless completion call.

Make budgets explicit and consistent: executed tools, attempted tools, validation failures, provider requests, total input/output bytes, elapsed time and optional spending. Decide which consume budget before changing API/CLI behavior. Human approval waiting needs a separate deadline policy from provider inactivity. The same rejection sequence must have the same documented effect across provider kinds.

Mint revocable external-agent grants bound to document incarnation, adapter instance/run, allowed methods and budget owner. Retire them on profile/document replacement and at the chosen terminal boundary. A retained proxy from a prior run must not address the current `self.session`. Keep the trusted renderer's capability separate.

Reconcile grant lifetime with persistent CLI reuse: a persistent adapter-session grant can authenticate the process while a server-side active-run binding authorizes each tool call. Reject unsolicited calls between runs unless an explicitly supported standalone MCP mode grants them. If a boundary revokes the credential itself, restart/reconfigure the process or use a negotiated refresh mechanism; do not leave a persistent MCP process holding an unusable token with no refresh path. Test idle old-proxy calls as well as late in-flight calls.

Move existing shielding, repeated-cancellation handling, unanswered-call settlement and private-directory/process cleanup intact before simplifying them. A cancellation callback must not mutate a replacement document. Parent shutdown must wait for owned cleanup up to an explicit bound, then record forced termination.

**Acceptance:** API, local, CLI and recipe paths pass the same invocation policy matrix: reject/edit, invalid parameters, pin/bypass policy, Stop at each lifecycle point, disconnect, branch switch, profile replacement, repeated cancellation and provider error. Completed pixels survive; pending approvals settle once; stale grants cannot mutate; superseded processes disappear; budget accounting is consistent.

**Delete:** duplicated CLI/API pause/budget/approval logic, CLI-specific turn fields in CoreApp, cross-module private helper imports and product workflow knowledge in protocol adapters where the shared owner replaces them.

## W4 Introduce explicit document and output identities

**Current owners:** `session/models.py`, `artifacts.py`, `session.py`, `branches.py`, `recipes.py`, `remix.py`, library ancestry and UI selection metadata.

Separate the following records. The table is a logical design, not a final SQL schema or requirement for one class per row.

| Record | Minimum meaning | Must not own |
| --- | --- | --- |
| Document | Stable ID, schema, name, active branch, creation metadata | Provider transport state or decoded image caches |
| Revision | Parent revision, structurally shared ordered invocation references, document metadata changes | Copied full historical image bytes or full membership duplication per edit |
| Branch | Stable ID, name, head revision, user/automatic retention classification | A deep copy of every message and step |
| Invocation | Stable ID, tool semantic version, canonical effective parameters, input bindings, actor, run and outcome | Mutable reassignment to a different logical operation |
| Output reference | Invocation ID and stable named port, with cardinality/member identity where needed | Dependence on positional array coincidence |
| Artifact use | Stable logical identity, blob ID, label, original/derived relationship, source evidence | Global first-writer provenance for every identical blob |
| Blob | Hash, byte length, encoded format, dimensions/frame metadata, storage location | User label, branch ownership or unique producing step |
| Source evidence | Acquisition/source URL/page/credit, original bytes, selected frame/page/crop and known limitations | Claims inferred from a hash alone |
| Run/conversation records | Typed messages, invocations/outcomes and bounded namespaced adapter continuation | A second document mutation history |

The engine continues to consume images and typed parameters and return outputs. Adapt that boundary to preserve the existing `OutputRecord.key`. Define named ports in tool metadata only for current output patterns. A list output needs stable element identity or an explicit rule that removing/reordering invalidates dependent bindings. Do not invent permanent identity for a search candidate merely because it once occupied slot 2.

Editing an operation creates a new version/revision with ancestry, rather than silently changing historical identity. The timeline can still display simple numbered steps. Evaluate dependent operations in deterministic order; parallel graph scheduling is not part of this package. Independent unchanged branches can reuse cache entries once their inputs and semantic fingerprints match.

Decide missing-output behavior now: if an edited multi-output step removes an output, descendants become explicitly unresolved/stale and require rebinding or an explicit frozen historical artifact choice. They must not silently continue using the old slot. Identical output bytes may still represent distinct logical edges and distinct attribution.

Write pure model/reference validators. They consume data plus a read-only artifact index, return validated structures/diagnostics and have no process, decoder, filesystem-policy or event side effects. Construct a live document/session only after validation succeeds.

Extend tool metadata for actual existing UI needs: named outputs, primary input, coordinate reference, bypass behavior, lock categories and finish-phase classification. Keep enums/parameters owned by Pydantic. Curated Quick ideas are views of those operations, not an alternative implementation. Version built-in recipes/templates when output semantics change.

**Migration:** schema 1–4 importers reconstruct bindings according to the old newest-preceding-producer and positional rules to preserve current meaning. Repeated step IDs in separate branches must not be merged accidentally. If historical bytes cannot identify a unique provenance/use, retain a legacy binding with an ambiguity marker and preserve the visible result. Do not invent evidence. Existing archives remain unchanged; new saves use a new explicit format version.

**Acceptance:** duplicate-byte sources keep distinct attributions; same-byte outputs bind independently; changed output count/order cannot redirect descendants silently; branch/save/open/bypass/replay preserve intended dependencies and pixels; old schemas migrate using an archived fixture corpus; unknown tools can be inspected/exported in a safe read-only compatibility mode when structurally valid.

**Delete:** reverse scans that infer producer identity from bytes, first-producer metadata as the sole provenance source, positional remapping where named bindings replace it, and duplicated ancestry reconstruction in recipe/remix/library code.

## W5 Replace copied histories with shared revisions

Store immutable invocation/message records once and let revisions/branches reference them. Start with a simple persistent parent-chain plus periodic materialized snapshot, or relational revision membership; benchmark both with real access patterns. Do not adopt an exotic persistent data-structure library merely because the concept is immutable.

Revision membership must itself use structural sharing/deltas or bounded materialized snapshots. Deduplicating operation records while inserting a complete N-row membership list after every edit still produces quadratic growth and does not satisfy this package.

Automatic before/after-turn checkpoints become revision pointers with a bounded retention policy. Named user branches remain durable until explicit removal. Allow promoting an automatic checkpoint to a named branch. Preserve the current last-turn undo behavior and clearly define what happens when a user starts editing a checkpoint.

Provider context invalidation follows branch/revision changes. Conversation views can share immutable message records but must not imply that a resumed external provider still understands a different branch. Annotation changes and creative preferences need explicit revision scope. Chat attachment references remain reachable even if their producing step is no longer on the active timeline.

**Acceptance:** metadata growth is approximately linear for the supported long workload, rather than the sum of all previous histories. Test branching before/after identical outputs, undo after partial/cancelled runs, named branch removal, checkpoint promotion and reopen. Active branch pixels/messages match the baseline. Retention never deletes a named branch or a blob reachable from another revision.

**Delete:** `deepcopy` of entire transcript/steps for each automatic turn and duplicate active-history serialization where revision references replace it. Keep old-format readers, not old-format live writers.

## W6 Move live state to transactional metadata and disk blobs

**Preferred design:** one local SQLite metadata store per workspace or a deliberately partitioned document store, plus immutable files named by content hash. Choose the scope in the prototype based on recovery/export/library ownership; avoid cross-database transactions for invariants that need atomicity. The database is authoritative. Derived indexes/thumbnails can be rebuilt.

SQLite is a proposed dependency through the Python standard library/runtime, not a claim that every bundled SQLite version is appropriate. Record the actual SQLite version and compile options in build/runtime inventory, use a maintained version, and test its configured journal/sync mode. WAL can help concurrent snapshots but adds checkpoint/backup responsibilities and same-host restrictions. Keep the live store in controlled local app data. Portable archives may be saved to user-chosen folders without treating those folders as live databases. [SQLite WAL](https://sqlite.org/wal.html), [atomic commit](https://www.sqlite.org/atomiccommit.html).

### Commit protocol

1. Validate the command and reserve its operation ID against a document incarnation/base revision. Record an operation intent if recovery needs to distinguish an accepted request from a lost response.
2. Capture immutable input references and resource grants. Release the document transaction before executing workers, provider requests or waiting for a user.
3. Write output blobs to owned staging files; bound size; verify bytes/hash/metadata; flush according to the chosen durability promise; publish immutable blobs without replacing unrelated content. Where power-loss durability is promised, include parent-directory publication durability on supported platforms; flushing file contents alone is insufficient.
4. Begin a short transaction, recheck document ownership and conflict policy, insert operation outcome/artifact-use/output-binding records, advance the branch revision and append the committed event/operation receipt.
5. Commit metadata before announcing durable success. Emit an event naming the committed revision. If notification fails, snapshot/operation lookup still reveals the outcome.
6. Release leases and schedule cleanup of unreferenced staging data. Startup repair can remove sufficiently old unreferenced staging blobs; it cannot delete committed references.

Metadata and filesystem writes cannot form a magic single ACID transaction. Order them so an interruption yields an orphan blob rather than a dangling committed reference. Test each crash point. Use leases/reference checks to prevent garbage collection racing publication or archive export. An export outside the blob store needs its own no-overwrite staging/receipt protocol and outcome reconciliation.

Define conflicts using the operation's dependency/read set, not an indiscriminate whole-document revision mismatch. An unrelated label/chat change can permit a deterministic result to commit to the next revision; changed input bindings, effective parameters, pins, approval conditions or network/resource policy require rejection, recomputation or renewed approval. Document/branch replacement invalidates ownership. Test both an unrelated revision advance and an approval-effective input change while work is outside the lock.

### Save and recovery semantics

Recovery opens the latest committed local revision. Explicit Save/Save As exports a stable revision snapshot into a portable archive. It can run outside the mutation critical section: the returned saved revision determines whether later edits remain dirty. A live database backup must use a consistent backup/snapshot mechanism, never copy only the main `.db` while ignoring WAL. [SQLite backup API](https://www.sqlite.org/backup.html).

Preserve the user's mental model: a project filename is a portable save, recovery is automatic local protection, and an unsaved indicator compares current revision with the last successfully exported revision. Consider a visible last-recovered/last-saved status rather than conflating them.

Archive open validates limits, paths, compression, schema, hashes and references in staging before activating the new document. It should not erase the active recoverable document on failure. Keep the current safe normalization of interrupted proposals/running steps. Never run historical tools during import.

CLI recipe generation becomes an explicit derived export from canonical invocations. If a compatibility `recipe.json` member remains in new archives, specify whether it is required and how conversion failure is handled. A perfectly valid project must not be unsavable solely because one parameter has no CLI spelling.

### Migrations and repair

Use ordered, versioned migrations in transactions. Before upgrade, create a verified backup/export and record the prior version. Provide a read-only integrity/diagnostics path and a repair operation that reports affected IDs rather than silently discarding data. Quarantine corrupt derived caches; committed project corruption requires preserving evidence and offering the last good revision.

Provide a small storage inspection UI: referenced versus reclaimable blobs, cache sizes, temporary work and last successful recovery commit. Garbage collection marks reachability from active document/branch heads, explicitly retained revisions/checkpoints, library entries, attachments and active leases, then sweeps unreferenced blobs after a grace period. Treating every historical revision as a permanent root would make reclamation impossible. Retention/compaction must materialize the state needed by retained heads before pruning historical reachability; retained audit metadata does not imply unlimited pixel undo. Run collection under the same ownership rules as mutations. Unknown/corrupt metadata is not permission to delete corresponding blobs.

**Prototype gate:** compare current and candidate storage on normal, long-history, branch-heavy and image-heavy projects. Require smaller bytes written per small edit, bounded memory, acceptable open/save latency, and pass crash/disk-full/corruption tests. If the prototype cannot meet these without excessive machinery, keep disk blobs and use a simpler incremental metadata journal while reconsidering the database scope.

**Acceptance:** kill before/after each blob/metadata/event boundary; reopen yields the previous or new complete revision, never a mixture. Disk-full errors preserve the last committed project. Saving revision N while editing N+1 leaves dirty state correct. Reopening exported archives on a clean installation preserves all referenced bytes. No committed artifact disappears during compaction. Recovery and backup are tested with real temporary files, not mocked return values.

**Delete:** full-archive autosave per mutation, in-memory ownership of every encoded image, duplicate persistence writers and indefinite live-format compatibility flags once the new path is default and accepted.

## W7 Bound execution, previews, IPC and media delivery

Maintain the current worker fault boundary. Replace whole-image dictionaries and raw pixel copies over multiprocessing pipes with validated immutable blob handles where measurements justify it. A handle must refer to an explicitly granted input under an owned storage root; it must not let a model request arbitrary host paths. Worker outputs go to owned staging locations and are validated before commit.

Validation must preserve that fault boundary: compressed-image decoding and codec inspection stay in a bounded worker. The core may verify hashes, byte limits and validated structural receipts; it must not reopen untrusted encoded images in-process merely to approve publication.

Introduce operation admission budgets: maximum decoded dimensions/frames, encoded input/output bytes, temporary disk use, total core-plus-worker memory, queue count, time and result/event bytes. Preserve existing tool-specific limits but account for concurrent buffers. Separate absolute operation deadlines from progress/idle deadlines; continuous progress must not extend an operation forever unless that class explicitly permits it.

Measure send/receive framing and partial IPC behavior. A worker timeout must cover work before/after the current receive loop, including serialization and blocked pipe writes. Do not fix synchronous blocking by spawning unbounded helper threads. A small bounded scheduler should prioritize document cancellation/control messages and visible previews over obsolete background thumbnails.

Previews use a captured document revision and immutable input bindings. New preview requests supersede/cancel older requests for the same owner. A stale completed preview may populate a content-addressed cache but may not become the current UI result or project output. Apply revalidates the requested operation and records it through the same invocation service; decide whether a verified cached preview can be promoted without re-execution.

Keep JSON for control/metadata; prototype binary image delivery for thumbnails/frames/full artifacts. Options are an authenticated loopback binary endpoint or a Tauri custom protocol with scoped artifact grants. Choose using native platform, browser-test and headless requirements. Do not expose arbitrary filesystem paths or put a bearer token in URLs that diagnostics logs. Enforce origin/auth/capability, representation limits and token revocation on the new path.

Representation cache keys include blob ID, frame, dimensions, color/encoding options and rendering version. Cache by bytes, not just query age/count; revoke object URLs and release leases on eviction. Separate full originals, working images, thumbnails, model images and animation frames so a small preview cannot accidentally fetch a giant original.

**Acceptance:** large valid media stays within measured memory/disk budgets; malicious/corrupt decode remains in the worker; a hung worker/partial IPC fails within a bound; rapid selection changes do not apply stale previews; many frames/thumbnails reach a stable memory plateau; exported bytes and engine pixel parity are unchanged; shutdown removes owned scratch/processes.

**Delete:** redundant base64/image copies where binary delivery replaces them, indefinite preview retention and unused per-component image caches. Preserve fallback transport only for a named supported client with a removal condition.

## W8 Replace broad UI invalidation with an explicit projection

Keep React Query for appropriate remote snapshots and Zustand for UI/local state. Add a thin document projection that consumes validated revisioned snapshots/deltas into normalized entities. It is a cache of the core, not a second domain implementation. Build indexes such as steps by ID, artifacts by logical use, visible image uses, outputs by operation and dependency/ancestry views from explicit core metadata.

Separate transient streaming text, progress, connection status, pending operations and approvals from the persisted document-shaped object. Batch presentation at a reasonable frame cadence. Final messages reconcile with committed records through stable identity. Do not persist every token or issue a full document request per delta.

For approvals, this separation concerns the transient waiter and whether its controls are actionable. Proposed steps, approval decisions, parameter revisions and terminal outcomes remain authoritative core records with the required persistence; they are not moved into an ephemeral frontend-only store.

Define query effects per command/event. Read-only settings or preview queries should not invalidate the whole document. Initial connection, detected event gap, complex replacement and explicit refresh can fetch a snapshot. Normal completed operations apply typed deltas or invalidate a narrow resource. If full snapshots remain simpler for small documents, retain that optimization only with revision checks and measured limits.

Window long timeline/chat/artifact lists and fetch thumbnails on visibility. Preserve selection, keyboard focus, pending approvals and assistive-technology navigation. Memoize completed Markdown and stable entities. Remove quadratic original-image filtering and repeated whole-history searches using explicit indexes. Unmount or lazy-load nonessential panels while deliberately retaining drafts in their feature owner.

**Acceptance:** streaming updates the active message without requerying/re-rendering unrelated histories; long-document scrolling/typing meets the measured budget; delayed snapshots/events cannot regress state; reconnect and core restart preserve appropriate drafts; object URLs/frames are released; no output bytes or save semantics change.

**Delete:** unconditional session invalidation, redundant local copies of authoritative domain state and ad hoc event casts. Do not rewrite all hooks/components at once; migrate one complete workflow and its selectors at a time.

## W9 Make providers independent and context bounded

Replace persisted OpenAI-shaped dictionaries with typed user/assistant messages, tool invocations/results, attachment references and run outcomes. Keep adapter-specific continuation data in a constrained namespace keyed by adapter/model/version. It is optional opaque state, never authority for the document. On provider/branch change, reuse only compatible continuation data; otherwise reconstruct bounded context from the document.

Introduce a deterministic context assembler. Allocate budget among immutable system/product instructions, latest user intent, selected/current artifacts, relevant operation dependencies, tool definitions, recent complete tool/result pairs, user changes and optional older conversation. Preserve unresolved pairs and pending approvals. Summaries describe history; they do not replace authoritative operation records. Prefer deterministic summaries before adding another model call for compaction.

Budget tokens when a trustworthy tokenizer is available and bounded bytes/estimates otherwise. Include tool schema size and images in admission. Expose estimated/actual usage and the reason material was omitted. Cache transformed provider images by blob/representation identity with a byte ceiling. Keep inspection/acquisition/continuation tools available and choose extra tool families explicitly; tool-selection optimization is not authorization.

Provider results should carry typed completion outcome, safe error category, retryability/advice, request ID where safe, actual model identity, usage, timing and optional cost estimate. Distinguish measured token/cost values from estimates/unknown subscription usage. Diagnostics should identify the failing boundary without logging prompts, full source URLs containing secrets, image bodies or keys by default.

Move local-model product strategies such as face-targeted laser eyes above HTTP/provider transport. They should consume typed outcomes, not parse `structured_data:` prose. Retain constrained one-edit behavior where it helps a small local model; make it explicit policy with a deterministic fallback/error path.

For CLI support, publish a compatibility manifest: discovered, launch-compatible, configured, verified version, known exclusions and exact evidence. Help flags alone are not verified behavior. Retain synthetic malformed-event fixtures and add sanitized recordings of actual supported versions. Live checks remain deliberate opt-ins with known credentials/cost, isolated configuration and cleanup.

Prototype ACP for one provider only. Exit criteria: equivalent authentication/subscription behavior, actual image input/output, BadShop-only tool access, edited/rejected approvals, deterministic budget semantics, resume/continue behavior, cancellation and descendant cleanup; meaningful bespoke code deleted. If it fails any product invariant, keep the existing adapter and report the limitation. Do not adopt draft capabilities merely because a library exposes them.

Define Retry versus Repeat. API continuation can resume known transcript state. An external provider that cannot reliably resume should offer “Continue from current result” with visible completed work, not imply exact replay. Stable invocation keys can deduplicate retried requests only when the upstream identity remains the same. A newly generated request is not safely deduplicated merely because its parameters look similar.

**Acceptance:** a supported long project remains within context budget; no dangling tool/result pairs; current branch/manual edits reach the model; local strategy survives presentation text changes; stale CLI grants fail; timeout/cancel settle identically; retry does not repeat completed export on the supported continuation path; diagnostics expose useful metadata without secrets.

**Delete:** provider-specific fields in common domain records, `getattr` capability switches, duplicated raw transcript repair/writers and legacy parser paths replaced by a proven negotiated adapter.

## W10 Reorganize feature ownership and accessible interaction

The feature layout should follow user tasks and lifecycle ownership: document/session; viewer/correction; timeline; chat/run control; materials/discovery/library; creative workflows; settings/onboarding; updates. Shared protocol/runtime/document/media modules supply validated state and operations. A directory move alone is not completion.

Extract connection startup/recovery, import coordination, appearance preferences, hotkeys and modal ownership from App. Extract provider profiles/onboarding, asset management, privacy policy and updates from the large settings composition. Feature components own drafts and view state; mutations remain commands. Use one operation-state helper only where semantics actually match; don't collapse “preview cancelled” and “save failed” into a generic spinner flag.

Build one dialog primitive/stack with focus entry/return, active-dialog ordering, inert background, Escape behavior, accessible title/description and busy/non-dismissible state. Test native WebView behavior before standardizing on HTML dialog or a library. A progress-only modal must still have a meaningful focus/announcement target. Keep approval ownership visible when other dialogs open.

Add a root recoverable render boundary and smaller boundaries around optional feature panels. A UI render error should leave diagnostics/reload/recovery available; do not restart the core automatically and risk losing unsaved state. Guard localStorage consistently and use safe defaults when persistence is unavailable.

Keep native close/recovery policy outside the failing App subtree, or deliberately reinstall it in the fallback. The current App/session-action lifecycle owns the native close listener, so unmounting it can remove the unsaved-close guard even when an error boundary successfully shows a fallback. Include render failure followed by native close in acceptance: require a safe explicit decision and retain recovery state.

Consolidate visual tokens for color, typography, spacing, borders, focus, density and motion across themes. Preserve the intentionally rough aesthetics while making contrast/focus/readability reliable. Theme styling should not change domain behavior. Keep text scaling, reduced motion and still-image previews. Separate layout/responsive rules from theme decoration to prevent each skin duplicating structural CSS.

Generated advanced forms should expose every supported parameter, while curated quick workflows show the minimum choices needed for a first useful result. Tool metadata supplies primary image, coordinate space and lock categories. User-facing source labels and provenance are readable; implementation IDs are available in diagnostics rather than dominating normal flows.

Localization is preparation, not an immediate translation project: centralize new user-facing errors/action labels, avoid using translated display text as identifiers, and test Unicode/long text/RTL-sensitive coordinates where relevant. Do not introduce a localization platform until languages/support ownership are chosen.

**Acceptance:** keyboard-only first-result → correction → branch → save/export workflow; modal focus cycle/return; large text/minimum window; all themes' critical contrast/focus states; reduced motion; source/import errors; screen-reader checks on supported native platforms; render-failure recovery. Automated accessibility checks complement, not replace, assistive-technology observation.

**Delete:** global DOM-query focus trap, duplicate modal state combinations, hardcoded tool semantics in multiple components and obsolete theme/layout overrides. Keep interaction tests focused on user outcomes.

## W11 Give reusable creative resources a lifecycle

Treat library entries, cast members/expressions, recipes, packs, challenges and remix shares as typed application features over the same document/blob system. They should not each invent independent ancestry, storage, cancellation and serialization rules.

Library entries reference blobs and provenance records, with indexed/paginated queries. A corrupt entry should appear as repairable/quarantined rather than prevent the whole library from listing. Content shared by multiple entries is retained until all references and leases are gone. Delete/compact should explain what is removed and preserve document-owned copies.

Source discovery separates query/candidate metadata from imported bytes. Record the selected source evidence and acquisition parameters; “refresh source” creates a new acquisition operation rather than pretending the remote web is deterministic. Apply Local only policy at network admission and on active operations. External URLs, local paths and derived thumbnails have distinct privacy/retention rules.

Extend the existing count-bounded local-media preview cache with explicit TTL/byte budgets, ownership and cancel/discard cleanup. Indexing a folder must remain bounded and must not upload it to a model. Preserve the existing changed-file hash refusal, and consider a clear relink/reimport path. Preserve page/time/crop evidence and original byte identity.

Recipes use typed canonical invocations and parameter slots with tool/recipe format versions. Validate the entire recipe before side effects; resolve user-provided inputs explicitly; execute through the shared invocation service. Persist partial completion/recovery without concealing failures. Recipe export to CLI is a separate representation.

Remix sharing chooses a dependency closure from a revision. Preview what source originals, provenance, chat, labels or personal metadata will be included. Existing selective-sharing protections remain. Do not include credentials, private paths or unrelated branches. Capture the exact export revision and validate on a clean import. A finished-image fallback stays available when editing dependencies cannot be safely included.

Challenges and rounds reference independent document revisions/results; starting one round cannot mutate another. Creation GIFs derive from selected committed outputs, with clear frame order/timing/size limits. They remain deterministic exports, not another editable-history source.

**Acceptance:** cast edit/reuse after reopening; recipe input substitution and interrupted recovery; corrupt library entry isolation; deletion without shared-blob loss; bounded preview cleanup; selective remix export/reopen with inspected contents; independent challenge rounds; creation animation exact frames/bytes. Use the existing playful-workflow journeys as the foundation.

**Delete:** duplicated ancestry/reachability scanners, bespoke per-feature blob stores where the shared store replaces them, unversioned recipe writers and superseded cache-retention implementations. Preserve existing bounds throughout migration.

## W12 Harden native lifetime and installed behavior

Keep the Rust shell focused on native window/application lifetime, process supervision, dialogs/clipboard/reveal, update installation and safe diagnostics. The Python core remains policy/document owner. Preserve updater policy leases and cancellation during Local only transitions.

Create a platform ownership matrix for shell → source wrapper/frozen core → workers → external CLIs → optional local inference → media subprocesses. For each edge specify owner, graceful signal, hard termination, descendant containment, timeout, handle/pipe cleanup and crash recovery. Test forced shell/core/wrapper termination on Windows, Linux and macOS before asserting equivalent guarantees. Existing Python jobs/process groups are valuable; investigate only demonstrated gaps.

Isolate the macOS delegate/quit bridge and its upstream assumptions. Prefer supported lifecycle APIs when they can preserve the close guard. If a private runtime hook remains necessary, pin/test the condition and fail with useful diagnostics instead of an unexplained startup abort. Do not claim this is an observed current macOS defect without native evidence.

Bound stderr continuously and diagnostics by bytes/lines. Correlate shell/core/worker logs with build/core/run/operation IDs. Preserve redaction and opt-in detailed traces. A support bundle should summarize state, versions and sanitized errors, not silently include private project images or conversation.

Measure updater peak memory, temporary disk use, cancellation after download, failed installer launch, interrupted install and restart/recovery. Prefer supported streaming/staged files if it reduces full installer buffers while preserving signature verification. Downloads and install prompts have explicit retention/cleanup; failed update does not erase user data.

Develop a capability design for file picks across Rust/Python before reducing Flatpak permissions: selected-file grants/portal descriptors, expiration and writable output ownership. Verify the actual installed package. Add OS publisher signing/notarization as a distribution workstream when identities/secrets/process ownership are available; updater signing is a different guarantee and already exists.

**Acceptance:** native close Cancel/Save/Discard, clipboard exact pixels, real file pickers, shell/core crash, owned process cleanup, local-only update cancellation, real upgrade and supported rollback. Retain package hashes, screenshots/logs and cleanup evidence. Browser prompts are not native dialogs; debug source launch is not an installer.

## W13 Reduce delivery cost while keeping the gates

Preserve exact-candidate release promotion, hashes, signatures, attestation, security audits and license inventory. Automate repeated native acceptance checks into typed receipts containing source/build/package identity, platform, test action, observed artifact/pixel result, cleanup result and evidence path. A nonempty evidence link is not itself proof that the expected workflow occurred.

Define support tiers and maintain them honestly: primary regularly tested platform(s), other release-qualified platforms, and experimental provider/package paths. Choose cadence based on available evidence capacity. Do not weaken a gate to make nightly promotion automatic; reduce promotion frequency or supported matrix explicitly if needed.

Track frozen-runtime imports and actual shipped inventory separately from inclusive build/development SBOM data. Measure PyInstaller payload composition, cold start and dynamic import requirements. Prune optional modules only when frozen smoke tests cover the supported feature matrix. A minimal installer with optional model/provider components is an experiment, not an automatic improvement: it creates download/update/version/repair obligations.

Keep source/frozen/headless feature contracts aligned. Lock dependency resolution; record Python/SQLite/codec/model/font and build-tool identities. Minimize dependency additions. Pinning a vulnerability-compatible version is not enough if dynamic packaging omits a runtime module; source tests and frozen-core smoke serve different purposes.

Extend architecture guards to new boundaries: pure document validation cannot mutate services; providers cannot execute tools/pixels; transport cannot own document policy; frontend cannot infer authoritative output edges; application callers use the shared invocation path. Introduce Python type checking incrementally at the protocol/document/run seams. Keep strict TypeScript; avoid exporting everything to silence unused-code analysis.

Maintain focused tests by promised behavior. Add property-based command-sequence checks and targeted fault injection for identity/replay/persistence. Use the existing negative-control review process for safeguards. Do not delete tests just to reduce line count or add giant loop tests to hide cases. Run broader Linux/browser/native/install suites only for shared changes, gaps, failures or release requirements, with the reason stated first.

**Acceptance:** a release candidate produces auditable evidence without manually retyping known facts; source and shipped version/resource identity agree; dynamic features still work in frozen builds; no fabricated pass for blocked/missing platform checks; maintenance reports show deleted old paths and explain growth.

## W14 Roll out, migrate and delete old paths

Ship compatibility readers before defaulting to the new format where useful. Use a fixture corpus across supported historical schemas and real anonymized/consented projects if available. During development, shadow only pure conversion/validation/projection; never execute tool/network/export side effects twice to compare old and new paths.

Rollout stages:

1. Release immediate repairs and metadata/protocol foundations with current persistence.
2. Exercise new document/storage in isolated developer/beta data, migrating copies. Compare rendered bytes, dependency bindings, provenance, branch heads, recipe behavior and recovery.
3. Offer an explicit save-copy migration with an automatic verified backup. Explain older-app read limitations. Refuse unsupported downgrade writes.
4. Make new storage/default format active after compatibility, performance and crash gates pass. Keep required legacy importers.
5. Remove legacy live writers, duplicated caches/executors and migration toggles after a stated support period and successful recovery exercise. Legacy readers can remain longer if their maintenance and security cost is bounded.

Each temporary adapter or feature flag needs an owner, actual users/formats supported, exit criteria and removal issue. No permanent “old or new, whichever works” fallback that conceals failed commits.

Rollback is code rollback plus data strategy. Before a new app touches user data, preserve a compatible original/archive backup. A prior app may open the original but must not overwrite the upgraded workspace. Supported downgrade export can be a separate future feature; do not imply it exists. Database migration failures leave a usable last-good store or an explicit read-only recovery path.

Consolidate the two study documents into one agreed product protocol. Observe install → own-image joke → revision → alternate take → export/share → save/reopen on verified candidates. Record real assistance, errors, output evidence and voluntary return; do not add hidden telemetry. Feature continuation/deletion decisions should follow this evidence. Architecture is successful when the next useful feature and the next difficult bug are easier to implement and explain, not merely when folders look cleaner.

**Acceptance:** old projects preserve visible bytes and disclosed limitations; new projects recover after failures; performance budgets hold on target hardware; native release gates pass; a beta user can return to their work; old execution/persistence paths are deleted; documentation describes final ownership rather than abandoned approaches.

## Proposed performance and resource acceptance

These are negotiation starting points, not measurements or public promises. Calibrate in W0 against primary hardware and native runtimes. Protect correctness first; improve a target or revise a supported workload explicitly rather than disabling validation.

| Scenario | Initial target proposal | Measurement |
| --- | --- | --- |
| Typing/selecting during a normal stream | p95 visible response under 100 ms | Key/pointer event to paint; count full-document fetches/renders |
| Cached artifact selection | p95 under 150 ms | Selection to correct rendered image, including metadata |
| Fresh thumbnail on normal local image | p95 under 500 ms | Admission/decode/transfer/render, cold and warm separately |
| Usable installed launch without optional model | Under 3 s on declared baseline hardware | Native renderer receipt plus loaded document/tool catalog; cold/warm separate |
| Small durable metadata commit | p95 under 100 ms on local SSD | Commit completion; archive export measured separately |
| Stop acknowledgement | UI feedback under 150 ms; owned execution ends within declared per-boundary timeout | UI receipt and actual process/worker termination separately |
| 100-turn history growth | Approximately linear metadata growth after shared revisions | Serialized/database sizes at fixed increments; preserve all named branches |
| Image browsing and frame scrubbing | Memory plateaus within configured cache budgets | Renderer/core/worker peak and retained bytes after idle/eviction |
| Small edit in image-heavy project | Writes proportional to changed metadata/new blobs | Filesystem bytes written; no full archive rewrite |
| Reconnect/replacement | No stale event application or duplicated mutation | Delayed/out-of-order delivery with persisted-output assertions |

Choose explicit byte budgets for thumbnails, decoded images, worker jobs, temporary disk and context after baseline measurement. The current 2 GiB encoded artifact capacity and worker RSS bound do not imply a 2 GiB whole-app bound. Large optional models have a separately disclosed resource profile. Performance evidence must state whether models/network/initial download are included.

## Cross cutting acceptance matrix

| User action or failure | Required visible outcome | Persistence/error/cleanup proof |
| --- | --- | --- |
| Import same bytes from two different sources | Two logical uses can show their correct labels/credits | One deduplicated blob, distinct provenance records after reopen |
| Edit a multi-output operation to remove/reorder output | Affected bindings are explicit and understandable | No silent fallback to an obsolete positional image |
| Reopen a branched project and preview/import again | Normal bounded image handling continues | Decoder/worker boundary retained; malformed input cannot move decoding into core |
| Save while another edit finishes | Saved revision is clear; newer work remains dirty | Archive is internally consistent and includes exactly the captured revision |
| Disk fills during export/save/commit | Clear failure with recovery options | Previous project/user file intact; no partial final-name export |
| Stop during provider, approval, worker or commit | Run reaches a clear terminal state | Completed work kept, unapproved work not run, callbacks cannot mutate replacement |
| Open another project with old events/results delayed | Only the new document is shown/changed | Incarnation/revision checks reject stale work |
| Provider completes export then loses connection | Continue/retry is honest about known results | Stable operation lookup or explicit outcome-unknown; no blind duplicate side effect |
| Switch provider/branch after a persistent CLI run | New context and authority match the chosen document | Old process/grant retired; continuation data not reused across incompatible scope |
| Build/nightly/tool/font changes | Saved pixels display; replay semantics are explicit | Cache identity changes for actual semantics/resources |
| Browse thousands of entries and frames | UI stays usable with progressive loading | Cache and DOM bounded; object URLs/temp data reclaimed |
| One library record or derived cache corrupts | Other valid content remains available | Quarantine/repair preserves source bytes and explains affected IDs |
| Toggle Local only while operations are active | Acknowledgement matches effective policy | Active network/update leases drained/cancelled under the existing core policy |
| Copy CLI command with punctuation | Command matches selected shell | Actual argv roundtrip and valid exported input bytes |
| Render exception or unavailable storage | Recovery/diagnostics remains available | No automatic destruction of the active core/document |
| Upgrade/install then reopen older project | Compatible work remains editable/viewable | Exact installed package, migration backup and hashes verified |
| Request old-app rollback after migration | Clear compatible-copy/recovery path | Older writer cannot overwrite newer-format data |

## Verification and evidence policy

Start each implementation with the existing owner/callers and the smallest test that distinguishes the promised behavior. Prefer a meaningful end-to-end workflow over many mocked assertions. For new identity/persistence/operation infrastructure, focused property tests and fault injection are justified because browser tests cannot reliably enumerate crash/interleaving boundaries.

Use the isolated `archlinux` WSL worktree and private toolchain on this PC for relevant Linux work. Reuse the task's Linux worktree and separate virtualenv. Select named Python tests first, then the one real browser/core journey crossing the changed boundary. Use private Xvfb for native process/WebKit/clipboard/close behavior; use the release workflow for actual installers. Do not use the user's real settings, projects, credentials or desktop input.

For justified full runs, follow the repository's `quick --core-workers 4` and `browser --browser-workers 2` guidance, apart from heavy builds; diagnose timing failures serially. Missing prerequisites, skips and timeouts remain unverified/failed as appropriate. A source debug run cannot be reported as installer evidence, and synthetic provider fixtures cannot establish a live CLI version's compatibility.

Retain logs, operation traces, screenshots where meaningful, output hashes, resource measurements and `summary.json` under `artifacts/verification/`. Include source/content fingerprints and exact selections. Apply the advisory diff review independently with concrete failure sequences and file/line evidence. Preserve negative controls for changed safeguards.

## Decisions to resolve at the relevant gates

These questions do not block immediate repairs or protocol work. They become explicit implementation decisions when their evidence is available.

| Decision | Default recommendation | Resolve by |
| --- | --- | --- |
| Primary supported workload/hardware | Normal 30–100-step projects plus tested long-history headroom | W0 measurements and product study |
| Workspace database scope | One local authority with transactional document/library references | W6 prototype and failure model |
| New project format number and legacy support window | New explicit version; preserve schema 1–4 import and originals | W4 migration ADR |
| Automatic checkpoint retention | Bounded automatic history, never silent named-branch removal | W5 product/space measurements |
| Resource/fonts portability | Record digests; package only where permitted/selected; disclose missing resources | W4/W6 provenance contract |
| Binary media transport | Smallest secure path supporting native UI and browser/headless testing | W7 benchmark/prototype |
| CLI support levels/ACP | Verified version matrix; ACP only after contract equivalence | W9 compatibility spike |
| Cost budgets | Actual where available, labeled estimates/unknown otherwise | W9 provider capabilities |
| Packaging/signing support matrix | Evidence-backed tiers and sustainable cadence | W12/W13 maintainer capacity |
| High-resolution/full-layer editing | Outside this modernization; separate product decision | Only after observed need |

The plan is complete when the current creative workflow runs through fewer, clearer authoritative paths; old projects remain safe; resource use has measured limits; provider changes stay in adapters; and future features no longer need to infer identity from pixel hashes or patch several independent lifecycle implementations.
