# BadShop state machines and repair ledger

Audit baseline: `361a0ef` (0.1.1), 2026-11-07. Worktree: `fix/state-machines`.
Linux verification uses a separate worktree at the same baseline plus this task's
binary patch: `/home/dan/.local/share/badshop-linux-test/worktrees/state-machines`.
It has its own editable Python environment; `linux/baseline.txt` and `linux/patch.sha256`
under the evidence root identify the transferred inputs.
This is the single audit file: machine definitions, reachable failures, grouped repair
issues, and verification evidence are maintained here. Issue IDs below are local work
items, not published GitHub issues. Pixel algorithms are outside this change.

## Acceptance criteria

| User action / interruption | Required result |
| --- | --- |
| Reopen a project saved while a model has outstanding calls | Unapproved steps remain rejected; provider history has one answer per call; no historical tool is executed during recovery; subsequent turns can proceed. |
| Retry a provider failure after manual changes | Current changes reach the model, without another user prompt or replaying completed tools. |
| Edit an approval while a later manual tool has finished | Reject forward dependencies before accepting the decision; keep the approval actionable. |
| Autosave fails transiently, then another operation or shutdown occurs | Keep recovery dirty until an atomic save succeeds; user Save status remains independent. |
| Import a file while changing documents or creative direction | Never insert the delayed import into the replacement; report a retryable error. |
| Disconnect, cancel repeatedly, or replace a connection | Pending requests/approvals settle exactly once; obsolete sockets cannot return the client to ready. |
| Replay a file-writing step | Execute its side effect again; never claim success from an old in-memory result. |
| Save/open/replay after a fix | Preserve artifacts, valid timeline ordering, and transcript consistency. |

## Scope and evidence rules

This audit follows executable ownership and persistence boundaries in `core/src/badshop`,
`app/src`, and the Rust supervisor. The reference CLI and design documents describe
intent; they are not assumed to describe the implemented transitions. State labels
below are either stored literals or named combinations of fields. Tool parameter enums
(filter names, layouts, providers, etc.) are choices, not lifecycle states. Procedural
pixel loops and PRNG state are not workflow machines.

The server supports overlapping UI and MCP requests. `Session` itself is **not thread
safe**: `CoreApp._blocking` serializes its mutations and holds the lock until the worker
thread finishes, even when cancelled repeatedly. Approval waits and provider/network
awaits deliberately release that lock. CLI requests run on separate WebSockets; losing
one cancels that request. Losing the last **user** connection also stops the managed
turn and cancels approvals. These are real interleavings, not parallel execution of two
pixel tools in the same session.

Tests use private temporary config/data/output directories and real session/project
operations. Provider replies, socket callbacks, and precisely positioned I/O failures
are controlled fixtures. No live provider or downloaded model is required. A mocked
scheduler reproduction establishes a permitted ordering; it does not measure how often
that ordering occurs in the desktop. This is a source audit with regression coverage,
not a proof that every possible failure has been eliminated.

## Prioritized repair issues

P1 means lost recovery or mutation of the wrong document; P2 means incorrect workflow,
stranded work, or false success. IDs are stable local issue groups. Each issue includes
its reproductions, implementation, and acceptance tests here instead of scattering
findings into separate files.

| Issue | Impact / priority | Confirmed baseline behavior | Fix / status |
| --- | --- | --- | --- |
| SM-01 | P1: loss of crash recovery after transient disk failure | `_autosave` cleared `_dirty` before writing; a failure left no pending retry, including at clean shutdown. | Fixed: clear recovery-dirty only after save succeeds. User Save revision remains separate. |
| SM-02 | P1: work applied to the wrong document/direction | Path import reads outside the lock then uses `self.session`; browser reads and result refreshes span replacement; auto-replay captures a Session but branch switches replace the timeline inside it. | Fixed: bind delayed core operations to both Session and timeline object; guard browser reads and returned imports with documentGeneration. Switching away and back still invalidates the old operation. |
| SM-03 | P2: impossible timeline dependency | An approval edit could give waiting step 1 an artifact produced by manual step 2. `edit()` guarded this but `run(raw)` and approval acceptance did not. | Fixed: share nonmutating parameter/dependency validation; reject bad approval edits while leaving their waiter alive; validate again at execution. |
| SM-04 | P2: approvals outliving their owners | Disconnect between proposal persistence and waiter registration escaped `cancel_all`; a second cancellation could abort CLI settlement and leave `proposed` with no owner. | Fixed: cancellation generation covers proposals in flight; shield the entire CLI cleanup to completion and retire its individual gate entry. |
| SM-05 | P2: replay reports a file write that did not happen | Export was a normal replay-cache entry with zero artifact outputs; the vacuous output-existence check always succeeded, even after the exported file was deleted. | Fixed: file-writing tools are excluded from initial and newly populated replay cache entries. Explicit replay exports again with never-overwrite naming. |
| SM-06 | P2: retry loses context about manual changes | API retry skipped `_changes_note`; completed manual edits after a provider failure were not announced as user changes on retry. The current step summary existed, but the action/change note did not. | Fixed: consume/record change notes on retry too; preserve the original user prompt and completed tools. |
| SM-07 | P2: contradictory connection state | `request()` allowed an OPEN but unwelcomed socket; timeout rejected connect without retiring its generation, allowing a buffered welcome during asynchronous close to publish ready. | Fixed: explicit authenticated state; terminal timeout/error/close retires the socket generation and settles waiters once. |

### SM-01 — retryable recovery writes

Reachable trace: import image -> `_changed` -> `_blocking` finally calls `_autosave`
-> disk write raises `EngineError`/`OSError` -> warning -> `_dirty == False` at baseline
-> a later no-op or `close()` does not write -> next launch has the previous recovery
image or none. This is separate from atomic-save protection, which correctly preserves
the previous file. Evidence: `test_autosave_failure_remains_retryable_without_another_edit`
in [test_state_machines.py](../core/tests/test_state_machines.py). The injected first
failure is followed by a real successful project write/open; user-unsaved stays true.

### SM-02 — delayed operations keep their original target

Path-import trace: start `_artifacts_import(path)` -> block `_read_import` -> New or
Create/Switch Direction -> release read -> baseline imports into the new target. Three
variants include switching away and back to the same branch. Auto-replay trace: hold
the session lock -> queue Edit -> queue Switch Direction -> release -> Edit schedules
auto-replay behind Switch -> baseline replays the other branch because `session is
self.session` is still true. The regression compares the destination's entire step,
including timestamps; it must be untouched. Tests: `test_slow_import_cannot_cross_a_document_replacement`
and `test_queued_auto_replay_does_not_run_in_another_branch`.

Core fixes are in [server/app.py](../core/src/badshop/server/app.py),
`_artifacts_import`, `_steps_edit`, `_auto_replay`. An import fails with an actionable
retry message; obsolete background replay is skipped. A new user action still works.
The object identity is deliberate: branch IDs alone miss an away/back round trip.
The corresponding browser race is independently confirmed in
`document-replacement.test.ts`: start FileReader, replace document, then complete the
read. Baseline sends artifacts.import into the replacement. `importBlob` now checks
documentGeneration before sending; no stale RPC is dispatched (`blob-before.log`).
There is also a result-side race: the old import succeeds, New completes while its
query refresh is awaiting, then App selects/attaches the old returned artifact. The
second browser-unit regression fails on that schedule (`import-result-before.log`).
The import action now rejects obsolete results before its callers can select them.

### SM-03 — approval edits obey timeline order

Reachable trace: CLI calls filter (step 1, ask-all) -> UI runs filter (step 2) on an
imported image -> UI edits step 1's approval to read step 2's output -> baseline accepts
and runs it, creating a forward dependency. The UI approval form exposes the session's
artifact choices; no corrupt project is needed. Tests exercise both the CoreApp gate
and direct `Session.run`, then approve the original valid parameters successfully.
Fix: [session/session.py](../core/src/badshop/session/session.py)
`validate_step_params`, used at edit, approval preflight, and edited execution.
`app/e2e/state-machines.spec.ts` additionally exercises the real browser approval
form, real core and worker: create a later manual output, submit the invalid edit,
observe its error and unchanged live approval, then approve the original successfully.

### SM-04 — pending approval ownership survives cancellation races

Two distinct reproductions share one lifecycle repair:

1. Block autosave after `Session.propose` has appended a CLI step but before
   `_cli_gate.request`. Call the actual `on_client_gone` handler, then release autosave.
   Baseline creates a new waiter after cancellation has already swept the empty gate.
   `test_disconnect_during_cli_proposal_cannot_leave_an_orphan_approval` fails waiting
   for the call to settle. After the fix it returns a rejected step without execution.
2. Cancel a CLI approval task while another operation owns the session lock; cancel it
   again while its cleanup waits for that lock. Baseline exits with a proposed step and
   cancelled gate future retained. `test_repeated_cli_cancellation_finishes_step_and_gate_cleanup`
   verifies rejected step, empty gate, and released cancellation tracking. The repeated
   cancel test exercises the CoreApp embedding boundary; the first uses the production
   disconnect handler. Neither assumes two pixel workers mutate a session concurrently.

Fixes: `CoreApp._approval_generation`, `_cancel_approvals`, `_cli_call`, and
[ApprovalGate.cancel](../core/src/badshop/agent/approval.py). `_to_the_end` is the existing
agent wind-up primitive, now also used for CLI cleanup. Unrelated CLI approvals are not
cancelled by one request's cleanup.

### SM-05 / SM-06 — retry must distinguish results from side effects

Export trace: `run_tool(export)` writes `exported.png` -> remove that private test file
-> `replay_from(export_step)` -> baseline returns done from memory without a file.
`test_replay_does_not_reuse_a_file_write` then verifies a second replay writes
`exported_2.png`, preserving the first file. Replaying is an explicit new write, not a
retry of an uncertain transport response.

Provider trace: provider failure -> user runs a manual filter -> `chat.retry`/`run_turn(retry=True)`
-> baseline bypasses `take_changes`. `test_retry_announces_intervening_manual_changes_without_repeating_prompt`
verifies the explicit change note, one user message, unchanged completed-step count,
and an empty pending change queue after retry. Existing
`test_retry_resumes_after_completed_tool_without_duplicate_user_or_tool` covers retry
when nothing has changed. Fixes are in `Session._executions`/`replay_from` and
[_Turn.run](../core/src/badshop/agent/loop.py).

### SM-07 — authentication and terminal connection ownership

Reproductions in [rpc.test.ts](../app/tests/rpc.test.ts) call the public RpcClient API
after socket open but before welcome, and schedule a buffered welcome after the
10-second handshake timer requests close but before the asynchronous close callback.
The latter is a closing socket, not an invented message delivered after a completed
browser close. Baseline publishes ready after the connection promise has rejected.
Additional assertions cover immediate retirement on error and successful fresh connect.
Fix: [rpc.ts](../app/src/rpc.ts) centralizes terminal handling and rejects requests
until authenticated. Already sent mutations are not automatically resent.

## Machine inventory and transition tables

### M1 — step lifecycle (explicit)

Owner: `Session` in `session/session.py`; persisted shape: `Step` in `session/models.py`.
States: `proposed`, `approved`, `running`, `done`, `error`, `rejected`, `stale`.
`approved` is accepted by the model/run/recovery code but no normal runtime assignment
sets it; approval decisions normally move a still-proposed step directly to running.
It is a compatibility state, not evidence of a missing transition bug.

Invariants: IDs remain unique in the active timeline; referenced artifacts resolve;
edited inputs cannot originate in this step or a later active step (earlier producers
and imports of identical bytes remain valid). Running clears previous result fields;
done has usable outputs/result and no error; execution errors have a message and no
current outputs. Stale intentionally retains the previous result/cache/error and is
not equivalent to a fresh run. Busy steps cannot be edited/replayed/deleted.

| From | Event / guard | To / effects |
| --- | --- | --- |
| absent | propose; actor/schema/image validation succeeds | proposed; append, emit, dirty |
| absent | validation fails | absent; clean error, no step |
| proposed / approved | run; optional user edit validates | running -> done or error; record timestamps/result |
| proposed / approved | reject | rejected; emit terminal result |
| done / error / stale / rejected | explicit Edit; no busy descendants, valid earlier inputs | edited step and non-rejected descendants become stale |
| stale | replay-cache hit for a non-file-writing tool with present outputs | done; fresh timestamps, copied results |
| stale | replay execution | running -> done/error |
| terminal / stale | Delete Last and it is last | absent; keep referenced artifacts/provenance |
| proposed | open a saved project after interruption | rejected, never auto-run |
| approved / running | open after interruption | error with recovery hint |
| any other run/reject/edit/delete attempt | lifecycle guard fails | unchanged + EngineError |

### M2 — replay and dependency propagation (implicit)

Owner: `Session.edit`, `replay_from`, `_executions`, `_advance`. States: up-to-date,
stale suffix, replaying, stopped-at-error (with `previous_outputs`), replayed. Invariants:
start at the earliest stale/failed predecessor that requires remapping; no busy step
in the replay suffix; rejected steps remain skipped unless explicitly edited; preserve
old output IDs across a failed replay/save/open/retry; remap in timeline order, with
the newest producer of identical bytes winning. Cache keys include engine version,
tool, normalized params and content-addressed inputs. They do not prove a disk write.

| From | Trigger | To / effects |
| --- | --- | --- |
| up-to-date | edit | stale suffix, old results retained |
| stale / terminal | Replay from N with no unresolved earlier dependency | suffix stale; snapshot eligible cache |
| replaying | cache hit | reuse done result; advance positional remap |
| replaying | successful execution | done; clear previous_outputs; advance remap |
| replaying | tool fails / is stopped | error at that step; save old outputs in previous_outputs; downstream stays stale with earlier successful remaps applied |
| stopped-at-error | edit/retry from that step | same algorithm; dependent refs follow replacement outputs after success |
| scheduled auto-replay | original Session or timeline replaced before lock acquired | skip; no destination mutation (SM-02) |

Output remapping is positional, not a semantic object tracker. `_advance` explicitly
retains an old artifact when the new output list has no corresponding position. Old
bytes remain stored. This is existing behavior to be aware of when replaying a source
or sprite-sheet operation with a different number of outputs; this audit does not
claim that the fallback identifies the user's intended new source.

### M3 — API agent turn, transcript, and retry (implicit)

Owner: `CoreApp._prepare_turn/_turn_main/_stop_turn`, `_Turn`, `run_turn`.
States: idle, preparing provider, completing/streaming, proposing, waiting approval,
executing, recording result, winding up, finished. Finish reasons: done, budget,
invalid_calls, provider_error, stopped, error. Retryable is an orthogonal marker tied
to the exact Session. Invariants: at most one managed turn/setup; Stop invalidates
setup generation; no late provider lookup starts work after Stop; every provider tool
call gets a result (including not-run) before the next request; no automatic replay of
completed tools on provider retry. Provider-request history is a disposable copy.

| From | Trigger / guard | To / effects |
| --- | --- | --- |
| idle | chat.send; not switching/closing | preparing under lock; reserve start generation |
| preparing | provider ready, generation still valid | active task; resolve attachments, bind Session |
| preparing | Stop/disconnect/close/cancel | drain lookup under lock; return stopped/error, no turn |
| completing | reply with calls | record assistant+calls; propose/approve/execute each sequentially |
| completing | reply without calls | finished(done) |
| proposing | invalid call | tool error answer; after max_invalid consecutive failures finish |
| executing | result | transcript tool answer; next call/completion until step_budget |
| active | Stop/error | cancel current step signal, finish in-flight mutation, reject remaining proposals, answer unanswered calls |
| completing | ProviderError | finished(provider_error), current Session retryable |
| retryable + idle | chat.retry for same Session | announce intervening manual changes; resume completion without adding user prompt |
| any retryable | new turn / branch activation | clear retry marker |
| saved history has unanswered calls | build_messages after reopen | `_answered` supplies interrupted results; no tool executes |

### M4 — approval policies and gate ownership (explicit + implicit)

Owner: two event-loop `ApprovalGate`s (managed API agent and CLI/MCP). Policy states:
auto, ask_changes, ask_all. Per-call gate states: absent, waiting, decided, cancelled.
Invariants: decisions consume a live waiter once; invalid decisions/params leave it
waiting; user-only editing validation is applied before consuming it; cancelled
request cleanup cannot leave a proposed step with no owner. Policy changes affect
future calls, not approvals already waiting. The gates do not execute pixel tools.

| State | Event | Next state / effects |
| --- | --- | --- |
| auto | any proposed agent tool | bypass gate |
| ask_changes | read_only tool | bypass gate |
| ask_changes | other tool, including export | waiting |
| ask_all | any tool | waiting |
| waiting | approve or valid edit | decided; future resolves; caller runs through Session |
| waiting | reject | decided; caller records rejection |
| waiting | invalid edit/decision or duplicate response | unchanged + error (duplicate has no waiter) |
| waiting / cancelled future | caller cancellation | retire entry, emit rejection, settle step under lock |
| proposal being persisted | generation changed by disconnect/replacement | reject before registering a waiter (SM-04) |
| any waiting | last UI gone, session replacement, shutdown | cancel_all; caller settles its own original Session |

### M5 — document revisions, Save, recovery, and replacement (implicit)

Owner: CoreApp, `session/project.py`. State is a product: current Session/timeline,
`path` or untitled, user saved/unsaved (`document_revision == saved_revision`), recovery
clean/dirty (`_dirty`), restorable offer or none, switching counter, closing flag.
Invariants: autosave never marks the user's document saved; document revision does not
repeat in one core lifetime; guarded replacement checks revision and explicit discard;
failed load/save preserves the previous live document/file; old Session events cannot
land on a new Session with reused step IDs. Recovery saves are atomic temp+replace.

| State | Trigger / guard | Result |
| --- | --- | --- |
| current | mutation | revision++, recovery dirty, user-unsaved |
| recovery dirty | locked call ends / close | atomic autosave; clean only on success (SM-01) |
| any current | Save/Save As; expected revision matches | atomic project write, path/saved_revision updated only on success |
| current idle | New/Open/Restore | reserve switching; validate under lock; replace; cancel old approvals; retire old CLI processes |
| switching | overlapping chat.send | reject; no turn on a changing document |
| guarded replacement | revision changed or unsaved without discard | refuse, preserve current document |
| New / Open success | replacement complete | baseline user-saved; Open retains project path unless it is recovery storage |
| Restore success | consume recovery offer | untitled/unsaved; recovery of it becomes current autosave |
| next core launch | claim_autosave | move session.badshop to previous.badshop before any new mutation; offer restore |
| project load | validate schema, sizes, IDs, hashes/decoders/refs | new Session or clean error; interrupted steps normalized |
| closing | Stop, drain work, final autosave, executor/provider cleanup | closed; no managed turn starts |

### M6 — creative branches and immutable artifacts (implicit)

Owner: `session/branches.py`, `session/artifacts.py`, `Session.visible_artifact_ids`.
States: unbranched; active branch with live timeline; inactive snapshots; deleted branch.
Artifacts: absent -> original/working/output stored by SHA-256 -> referenced or retained.
Invariants: bytes never mutate under an ID; active timeline is authoritative over its
possibly older stored snapshot; inactive timelines are deep copies; project save keeps
branch references; branch activation invalidates provider resume/retry context.

| State | Trigger | Result |
| --- | --- | --- |
| unbranched | create direction | snapshot Original, create/activate copy |
| active | create from finished step | snapshot outgoing; truncate new steps/messages; clear truncated provider transcript |
| active | switch to another existing branch, no busy steps | snapshot outgoing; deep-copy target into live data; new timeline identity |
| active | switch to itself | no change |
| inactive | rename/remove | update/remove snapshot; active removal refused |
| artifact absent | import/output | validate pixels, content-address bytes and metadata; imports retain originals |
| artifact present | identical bytes again | deduplicate, retain first metadata/provenance |
| completed step deleted | delete last | artifact retained if needed; IDs not reused while provenance/messages reference them |

### M7 — worker process and cancellation (implicit)

Owner: `session/worker.py` (`_call_lock`, `_state`, process/pipe, cancel events).
States: absent, starting, ready, executing, stopping/dead, closed. Invariants: one
ToolCall in flight per executor; a per-call cancellation applies even before execution;
global cancel applies to the current call only; no unconsumed old outcome survives a
crash/exception; close is terminal. InProcessExecutor intentionally cannot interrupt
a running tool; it is used by unit tests, not claimed as native-worker coverage.

| From | Trigger | To / effects |
| --- | --- | --- |
| absent/dead | run, not closed/cancelled | spawn; wait for startup handshake |
| ready | call | executing, send complete validated inputs |
| executing | outcome | ready; reuse process unless crashed |
| starting/executing | timeout, RSS limit, cancel, death, broken pipe | kill owned worker/children; error outcome |
| executing | progress | forward progress; extend deadline for asset transfer |
| idle after heavy call | memory threshold | drop model cache in worker |
| any | close | set closed/cancel under state lock; acquire call lock; drain/stop worker |
| closed | run | refused; never respawn |

### M8 — subscription CLI process and MCP request (implicit)

Owner: `providers/cli_provider.py`, `providers/cli_turn.py`, `mcp/proxy.py`.
CLI states: configured, launching, streaming, completed/reusable, stopped, closed;
session_id is separate resume state. MCP calls: connecting, authenticated, running or
awaiting approval, gathering output images, completed/error/cancelled. Invariants:
only BadShop tools are proxied; each RPC request gets its own socket; cancellation
closes that socket; tool execution is CoreApp-owned; one failed provider turn does not
replay historical tools automatically. Heartbeats stop in finally.

| From | Event | Result |
| --- | --- | --- |
| configured/stopped | CLI turn | spawn owned process tree; Claude stdin prompt or one-shot argv |
| streaming | session event | capture provider resume ID |
| streaming | text/snapshot | normalize deltas; avoid repeated snapshots |
| streaming | done | Claude process reusable; Codex/Gemini await exit; record assistant answer |
| streaming | parse failure | report raw event, keep reading |
| streaming | provider error/exit without done/Stop | stop owned process tree; record partial text if any; report reason |
| reusable | next turn | Claude stdin reuse or new one-shot process with resume ID |
| any | branch switch/session replacement/shutdown | retire/close processes; clear inappropriate cached resume context |
| MCP authenticated | tools.run | CoreApp proposal -> approval -> execution; errors returned as tool errors |
| MCP call cancelled | disconnect | cancel only that request; shielded settlement (SM-04) |

### M9 — transport, renderer reconnect, and native supervisor (explicit + implicit)

Owners: `server/ws.py`, `app/src/rpc.ts`, `app/src/data.ts`,
`app/src-tauri/src/supervisor.rs`. Server states: awaiting hello, authenticated(user/CLI),
closing, closed. UI states: starting, connecting, ready, disconnected, failed; recovery
is an extra flag. Native supervisor states: starting, ready, failed, stopped, attempt 0–3.
Invariants: token/actor check precedes dispatch; one writer orders responses/events per
socket; request IDs correlate replies, **not** deduplicate operations; obsolete socket
generations cannot publish events; recovery does not expose an empty replacement before
restoring previous work; at most three automatic core restarts after the initial launch.

| Machine / from | Trigger | To / effects |
| --- | --- | --- |
| server awaiting hello | valid token and allowed actor within 10 s | welcome; subscribe; user connection count++ if appropriate |
| server awaiting hello | invalid/timeout/binary | policy close; no RPC execution |
| server authenticated | request | independent task; methods may overlap, mutations still locked |
| server closing | socket lost | unsubscribe, cancel/drain its requests; last user triggers on_client_gone |
| client disconnected | connect | increment generation; authenticate new socket |
| client connecting | welcome in current live generation | authenticated/ready |
| client connecting/ready | timeout/error/close/replacement | retire generation; reject pending calls; no automatic mutation resend |
| UI disconnected | bounded reconnect timer | retry connection up to three times with 750 ms × attempt delay |
| UI core identity changed | connect then recovery snapshot | restore autosave or show recovery error; preserve drafts until outcome |
| native starting | valid stdout handshake within 30 s | ready; drain stdout and monitor child |
| native running/start failed | unexpected exit/startup failure | restart while attempt < 3, otherwise failed |
| native failed | explicit Restart | reset attempt; starting |
| native any | Stop/drop/normal app exit | close stdin; wait up to 5 s then kill/reap; stopped |

### M10 — user Save/Discard/Cancel and form drafts (implicit)

Owners: `sessionActions.tsx`, `ToolForm.tsx`, `App.tsx`, `data.ts`, `store.ts`.
States: no dialog, awaiting choice, saving/picking path, replacing/closing, error with
dialog retained. Form states: synced, locally edited, remotely changed, conflict,
submitting. Import states: reading, requesting, refreshing, returned, obsolete/error.
Invariants: snapshots and revision tokens protect destructive replacement;
cancelled pickers preserve work; a failed save keeps the dialog open; automatic events
merge independent parameter edits but require resolving same-field conflicts. A document
generation change resets selection, coordinate pick, attachments and drafts.

| From | Trigger / guard | To / effects |
| --- | --- | --- |
| no dialog | new/open/restore/close request | snapshot; clean idle document proceeds, otherwise awaiting choice |
| awaiting choice | Cancel | close dialog, resolve false |
| awaiting choice | Save | fresh snapshot + revision checks; picker if needed; atomic server save; recheck before replace |
| awaiting choice | Discard | revision-guarded replacement; explicit discard flag |
| closing with active turn | continue | stop first, refresh expected snapshot, then Save/Discard |
| saving/replacing | error/concurrent edit | keep dialog and refresh baseline; require another choice |
| form locally edited | new server params | three-way merge; conflict blocks submit |
| submitting | success/failure | settle busy in finally; preserve/reconcile editable values |
| coordinate pick | complete/cancel/document replacement | fill bound field or clear pick |
| blob reading | document generation changed before read finishes | refuse before RPC; ask user to import again |
| import refreshing | document generation changed before action returns | discard obsolete result; refuse selection/attachment by that caller |

### M11 — asset transfer and resumable partials (implicit)

Owners: `engine/assets.py`, `engine/manifest.py`, CoreApp downloads, Settings progress.
States: missing/invalid, valid cached, claimed partial, downloading, verifying,
published, cancelled/failed with reusable partial or discarded partial. Invariants:
one manual download per name per CoreApp; concurrent engine/manual writers have separate
staging directories; no partial masquerades as a valid final asset; resume requires a
pin or validator; success means final size/checksum checks passed. Cancellation of the
async waiter sets a signal but the download thread remains owned until completion.

| From | Trigger | To / effects |
| --- | --- | --- |
| valid cached | request | return file |
| missing/invalid | request | claim idle partial by rename or create private staging |
| partial | safe offset/validator | Range + If-Range request |
| partial | server ignores range / responds 416 | restart from byte zero (one fresh fallback for 416) |
| downloading | chunks | write staging, progress; bounded socket timeout, cancellation checks |
| downloading | short transfer/cancel/transient error with safe partial | retain idle partial for explicit retry |
| downloading/verifying | invalid range/size/checksum | discard invalid staging; actionable error |
| verifying | valid full bytes | atomic replace final path; concurrent valid winner accepted |
| any task end | finally/callback | retire download ownership and temporary directory |

### M12 — local media, collections, reusable library and packs (implicit)

Owners: `session/media.py`, `local_collection.py`, `library.py`, `packs.py`; server APIs
serialize their mutations. Media states: selected source, extracted/frozen preview,
selected candidates, imported, expired. Collections: unindexed, indexed-current,
source changed/moved, reindexed, removed. Library/pack: absent, validated/staged,
installed, metadata-updated, removed. Invariants: imports verify frozen bytes/hashes;
current session keeps original provenance; metadata never silently authorizes a local
path for the agent; corrupt input is checked before commit where the API promises it;
removing library entries does not delete shared content needed by other entries.

| Machine / from | Trigger | Result |
| --- | --- | --- |
| media source | preview with limits and safe local decoder | freeze extracted PNGs + metadata; expose thumbnails/selection IDs |
| preview | valid selection/crop | verify candidate hashes, import; crop/animate becomes normal session tool step |
| preview | cache evicted / changed pixels | refuse; request fresh preview |
| collection absent/current | index/reindex | bounded traversal; hash images; preserve tags only for unchanged bytes; atomic index replace |
| collection indexed | import | verify path containment/no new links and unchanged hash; import + provenance note |
| collection changed/moved | import | refuse; reindex first |
| library absent | save asset | write immutable blob(s), then atomic entry metadata |
| library installed | import | validate/decode all blob(s), then add to session and persist metadata note |
| library installed | update/remove | atomic metadata update or remove record; retain shared blobs |
| pack selected | import | validate all members/hashes/limits first; write blobs, fresh entry IDs; roll back installed entry records on failure |
| built-in pack | install | generate deterministic engine artwork, save entries; reinstallation is additive |

### M13 — provider profiles and settings (implicit)

Owners: `providers/profiles.py`, CoreApp provider/settings methods. States: absent,
saved, selected, resolving credentials, ready/unsupported/error, retired. Secrets and
profile persistence are separate resources. Invariants: session/project contains a
profile ID, never its key; a profile cannot reuse another profile's key reference;
failed config write must preserve the working key; provider changes require idle;
worker replacement/settings changes serialize with tool execution.

| From | Trigger | Result |
| --- | --- | --- |
| absent/saved | save with new API key | write fresh key slot, commit profile, clean old slot; rollback new slot on config failure |
| saved | select | session profile ID changes, document dirty |
| saved | test | report capabilities/status; live probe only when explicitly requested |
| selected | start turn | resolve credentials under reserved setup; failure leaves no running turn |
| saved/selected | delete idle | commit removal; clean key; clear selection if active |
| settings current | valid update | persist first; update runtime; retire executor if limits changed |

### M14 — standalone CLI command/history/recipe (implicit)

Owners: `cli/main.py`, `filestore.py`, `recipes.py`, `chat.py`. Standalone pixel commands
use FileStore, not desktop Session; terminal `chat` uses CoreApp and inherits M1–M5.
States: parsed, validated, executing, written/logged, failed; recipe adds validated
sequence, running step i, stopped-on-error, completed. Invariants: recipe cannot call
itself, output path checks precede execution, command history records successful
commands; recipe collapse of repeated output paths preserves first slot order.

| From | Trigger | Result |
| --- | --- | --- |
| argv | parse/validate | typed engine command or nonzero usage/error |
| validated | execute | FileStore output(s), successful history entry; failure exits without success log |
| history | recipe export | collapse commands with same output path, preserve order, write recipe |
| recipe input | validate variables/tools/output scope | sequential execution or refusal |
| running recipe | step nonzero | stop; prior outputs remain (not a transaction) |
| terminal chat | /save, /open, /restore, /retry, Ctrl-C/EOF | corresponding CoreApp lifecycle; stop/close and autosave on exit |

## Boundaries and ruled-out suspicions

- Recovered unanswered tool calls already have a repair in `agent/context.py::_answered`.
  They remain historical data on disk, but every provider request gets completion
  placeholders. No redundant recovery rewrite was added.
- `_blocking` already defers repeated cancellation until its thread exits. The CLI bug
  was cleanup cancelled **before acquiring** that lock, not a missing mutex around tools.
- Worker cancellation/timeout/crash already retires its pipe/process; the next call
  cannot consume the previous call's result. Existing worker tests cover restart.
- Project saves already use temp+fsync+replace; SM-01 fixes pending retry ownership,
  not torn zip files. Export uses exclusive creation and never-overwrite names.
- Replay cache is appropriate for stored deterministic artifacts. It is inappropriate
  for external side effects; only that eligibility changed in SM-05.
- Duplicate JSON-RPC IDs are correlation, not idempotency keys. The UI does not resend
  mutations automatically; MCP clients that deliberately issue a second tools.run
  create a second step. Provider/HTTP/network transport exactly-once execution is not
  claimed, and cancelled client promises do not roll back completed disk writes.
- Direct simultaneous calls to Session from arbitrary threads are outside its contract.
  Concurrency tests use CoreApp's lock and real async boundaries. Multiple independent
  desktop cores sharing one config/data folder are not coordinated by this lock.
- The legacy API allows session replacement without a revision token; the desktop
  supplies tokens. That compatibility behavior is not described as guarded replacement.

## Verification record

PR merge update: merged `main` at `551585f`. The only conflict was in
`app/tests/document-replacement.test.ts`: retained both new import regressions and
main's removal of three redundant replacement cases. No production-code conflict.
Linux revalidation of the merged tree passed all 14 document/RPC tests and `tsc -b`;
evidence is under `artifacts/verification/state-machines/merge/`. Earlier full-suite
counts below describe the original audit revision, before main's test consolidation.

Evidence root: `artifacts/verification/state-machines/` (ignored generated artifacts).

| Evidence | Result / meaning |
| --- | --- |
| `regressions-before-unsandboxed.log` | 9 failures on baseline behavior: SM-01/02/03/05/06; exact cases above. |
| `approval-before.log` | 2 failures before SM-04: orphan waiter and interrupted cleanup. |
| `rpc-before.log` | 3 failures before SM-07, 6 existing cases passed. |
| `blob-before.log` | Delayed FileReader regression failed before its guard; 6 existing cases passed. |
| `import-result-before.log` | Obsolete import-result regression failed before its guard; 7 cases passed. |
| `core-fixes.log` | Initial 9 core regressions passed after their fixes. |
| `rpc-after.log` | 9 connection tests passed after SM-07. |
| `core-targeted.log` | 146 passed, 1 skipped, 1 assets-status timeout; the timeout passes in the final recheck. |
| `core-final.log` | 13 passed: all 11 new core cases plus assets-status and real JSON transport timeout rechecks. |
| `quick/summary.json` | Initial attempt blocked by mismatched pnpm store selection before checks; not a pass. |
| `quick-retry/summary.json` | Full quick: lint, 6 workflow tests and Rust format passed. Core: 1,642 passed, 52 skipped, 24 deselected, 69 failed; classified below. Frontend ran before the last import fix and failed its regression; build caught an incomplete test mock, now corrected. Rust was blocked by that build. |
| `baseline-comparison.log` / `.json` | All 69 failed core cases rerun against unchanged production core: 68 failed identically, 1 JSON transport case passed. |
| `final-quick/summary.json` | Final frontend: 87 passed across 17 files; lint and 2 Rust supervisor tests passed. |
| `browser/summary.json` | Production TypeScript/Vite build passed; 34 existing browser workflows passed. New approval workflow initially failed due to test locators (required-field label and global error banner), corrected below. |
| `approval-ui/summary.json` | Intermediate new-test locator failure; trace shows the expected error in the global alert and the approval still waiting. |
| `approval-ui-final/summary.json` | Corrected new browser workflow passed against real core/worker: invalid edit, retained approval, then successful original approval. |
| `linux/quick/summary.json` | Entire Linux quick suite passed: 1,726 core tests, 87 frontend tests, 6 workflow tests, 3 Rust supervisor tests, lint, Rust formatting, production build and dependency setup. Core: 39 skipped and 24 deselected. Includes the new regressions and platform-sensitive baseline failures. |
| `linux/desktop/summary.json` | Native prerequisites/build, direct debug launch and `start.sh` launch passed in private Xvfb. Both observed a rendered window, established renderer/core TCP connection, successful main-process close and no surviving owned children. Screenshots: `native.png`, `launcher.png`. |

All 17 added regression cases pass: 11 core cases, 3 RPC cases, 2 document/import
cases, and 1 real browser/core workflow. The browser coverage is 34 existing passing
workflows plus the corrected new passing workflow; the initial full browser run is
retained as failed rather than relabeled. No production change followed that run.

Focused reproduction commands from the checkout root (after the development setup):

```sh
uv run --project core pytest core/tests/test_state_machines.py -q
pnpm --dir app exec vitest run tests/rpc.test.ts tests/document-replacement.test.ts
pnpm --dir app exec playwright test state-machines.spec.ts
```

Repository-wide verification uses `./verify.sh quick` and `./verify.sh browser`.
On this Windows host their entry point was invoked directly with the checkout's
Python: `scripts/verify.py quick|browser --output <evidence-directory>`. Failed layers
were rechecked selectively. After the Linux toolchain became available, quick and
native desktop verification were also selected through the user's WSL launcher;
their final results are in the table above. The Linux launcher check used
`BADSHOP_DEV_PORT=1438` to avoid other tasks' ports. Installer coverage remains outside
this task. The task's Linux worktree and complete evidence were preserved, and Linux
logs/screenshots were also copied to this Windows worktree's evidence root.

The 68 reproduced baseline failures include Windows path/golden-text assumptions,
POSIX permission checks, symlink privilege requirements, Unix executable-script CLI
fixtures, a terminal CRLF expectation, and a WebSocket close-test assertion. They are
not counted as fixed or passing. The comparison checkout advanced independently to
`88aa591` (test-only changes); `git diff 361a0ef 88aa591 -- core/src` is empty. Exact
comparison revision and node IDs are retained in its JSON. The remaining JSON transport
timeout and the separate targeted assets-status timeout both passed in `core-final.log`;
this is a successful recheck, not a claim that the original full run was green.

Native evidence limits: the harness checks TCP establishment, not the UI's completed
authentication/recovery state. Both retained screenshots still show "Connecting";
browser workflows provide the ready-state and interactive verification. The first
direct native run logged `corrupted double-linked list` during teardown, despite the
main process exiting successfully and cleanup assertions passing. It was absent from
the launcher log and the baseline native logs (copied as `linux/baseline-*.log`). Its
origin is not established; it is retained as an unattributed native diagnostic, not
claimed fixed or assigned to these application state transitions. Native dialogs,
clipboard interactions, installers, and live providers were not exercised.

Windows sandboxing blocked asyncio's own loopback socket creation; the first sandboxed
attempts could not run async tests. Those owned test processes were stopped, and the
suite was rerun with approved local socket/process access. The original checkout's
source and unrelated processes were preserved. Linux verification used the authorized
`archlinux` WSL 2 launcher and isolated Xvfb, without driving the user's desktop.
