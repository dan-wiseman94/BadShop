# Architecture modernization implementation status

Implementation baseline: `fb1ad675546bd466d5578fbf324a72361458a619`.
The five audit documents were inherited task material, retained in checkpoint `2f8316c`. The full W0–W14
plan remains authorized. Earlier sections below are chronological checkpoints; the final
continuation records current implementation and distinguishes external acceptance gates.

## Implemented

- W2 protocol increment: protocol/build/process negotiation, document incarnation,
  branch/revision/event ownership, ordered delivery, gap refresh, malformed-frame
  rejection and queued-command ownership checks. The handwritten method map is
  replaced by schemas/types generated from actual handlers and response models.
  Input defaults remain optional; serialized model defaults are required. Runtime
  client validation reuses the existing CSP-compatible schema validator.
- W3 run increment: one run object owns task/configuration, CLI reply identity,
  streamed text and one terminal outcome. Snapshots recover a missed failure/retry
  notice and emitted partial reply. Late callbacks cannot publish into another
  run. API and CLI paths share execution budgeting and finish-tool classification;
  rejected proposals do not consume budget, and parallel approvals cannot overspend.
  Revocable adapter credentials now bind calls to the document, direction and
  active run; idle discovery remains available. Stop revokes queued work, and
  old sockets cannot borrow a later run. Document/branch/profile replacement
  retires credentials and private provider directories. Standalone MCP proxies
  retain their first document/direction across per-call reconnects.
- Shared invocation increment: the session owns budget admission and approved
  edit settlement for API and CLI calls. Removed the duplicate CLI execution
  helper. Budget slots are reserved immediately before execution, so cancellation
  cannot lose accounting after a completed tool. Manual and recipe execution
  continue through the same session validation/execution owner. Full parent
  operation/resource/deadline policy remains open.
- Cancellation records retain step objects rather than reusable display labels.
  Late cleanup cannot cancel or remove a replacement document's same-label step.
- Recipe Stop accepts progress revisions within the same document/direction,
  while refusing another incarnation. Completed pixels survive cancellation and
  autosave recovery. This does not add crash-durable batch operation receipts.
- Native updater explicitly negotiates protocol 1 before polling update HTTP.
  A shared welcome fixture is checked by Python and Rust. Missing/incompatible
  protocol replies fail closed; the existing lease/cancellation owner is retained.
- Onboarding uses the existing guarded preference helper, so disabled browser
  storage cannot prevent the workspace from rendering.

- W1 decoder boundary: project branch reference validation now calls a data-only
  reference collector instead of constructing another live Session against the
  shared artifact store. Session construction without a decoder no longer clears
  a decoder already configured on the store.
- Extended the real worker/image/project regression to create a branch, save,
  reopen, decode the restored animation and import another image while parent
  decoding is forbidden. Existing pixel and process-cleanup assertions remain.
- W1 export publication: complete, flushed sibling files are published using
  non-replacing rename on Windows or hard-link publication on POSIX. Write,
  flush and close failures remove staging files; concurrent files are preserved.
  POSIX filesystems without hard links fail safely with the normal export error.
  This does not promise power-loss directory durability.
- W1 replay identity: source-content fingerprints join the version/runtime key.
  PyInstaller's spec bundles the fingerprint of the exact package source. Source
  edits at an unchanged version invalidate executions; saved image bytes remain.
- W1 CLI lifecycle: a successfully saved changed profile retires its idle cached
  processes and private directories immediately. Failed profile saves keep the
  working process. Finished branch retirement drops its retained references.
- W1 frontend: completed source operations invalidate source health using the
  emitted `step.finished` event. CLI copying builds argv first and formats it for
  POSIX shells or PowerShell on Windows, including literal apostrophes.
- W1 diagnostics: running stderr rotates at 2 MiB with one previous file;
  overlapping retired readers serialize publication. Oversized legacy logs are
  trimmed on rotation. Diagnostic reads inspect at most 64 KiB and 200 lines.
- W0 measurement/invariant work: added the linked
  [ledger and workload instructions](audits/2026-11-13/invariants-and-workloads.md).
  Extended the existing resource reporter with actual history/checkpoint/archive
  workloads, raw timing samples, bytes, RSS, hashes and explicit failure evidence.
- W5 bounded checkpoint increment: at most ten marked automatic directions are
  retained, protecting active/latest-undo directions. Explicit, renamed, selected
  and legacy unmarked directions are permanent. Markers survive save/reopen.
  Structural sharing and the new document graph are **not** implemented.

## Verification

Isolated Linux worktree:
`/home/dan/.local/share/badshop-linux-test/worktrees/architecture-modernization`.
It has its own verified editable environment and can be reused for follow-up work.

Focused `test_decode_worker.py` and `test_project.py`: **135 passed**.
Evidence: `artifacts/verification/modernization-decoder/summary.json` and logs.
Additional retained evidence (all paths below `artifacts/verification/`):

| Evidence directory | Actual result |
| --- | --- |
| `modernization-export` | Session/export and atomic helper: 28 passed |
| `modernization-replay-cli-fixed` | Execution/replay, profile persistence, real fixture CLI retirement: 97 passed |
| `modernization-retention` | Branch/archive/undo, build replay and failed/successful CLI replacement: 16 passed |
| `modernization-frontend` | Stream/source invalidation and CLI formatting: 7 passed |
| `modernization-shell-roundtrip` | CLI tests including actual POSIX received argv: 4 passed |
| `modernization-negative-controls` | Original decoder/export/CLI-retirement implementations fail new tests; fixed implementations pass. Separate retention proof checks branch-count growth. |
| `modernization-browser` | Real browser/core manual editing, replay, fresh-process reopen and exported bytes: passed |
| `modernization-branches-browser` | Real branch counts, previews, timeline edits and reopen: passed |
| `modernization-desktop-final` | Linux native debug build, private Xvfb recovery/clipboard/dialog/close workflows and development launcher: passed |
| `modernization-final` | Lint, generated types, 5 Rust supervisor tests, checkpoint visitation, import contracts, Vulture, Knip: passed. Rust formatting initially failed and was corrected; subsequent direct `cargo fmt --check` passed. |
| `protocol-schema-browser` | Six real project journeys passed with runtime validation, including damaged-file recovery and exact exported bytes |
| `protocol-contract-checks` | 158 RPC/library/media/retro tests passed; one registration assertion initially misstated the handler's default and was corrected. Five generation/evidence regressions passed. One environment-specific test skipped. |
| `protocol-command-ownership` | 17 document/ownership tests passed; the remaining registration assertion was corrected and passed in `invocation-budget` |
| `protocol-owned-browser` | Real manual import/edit/replay/save/fresh-process reopen/export passed with request ownership |
| `protocol-owned-controller` | Provider rejection/error/retry and production-CSP workflows passed |
| `invocation-budget` | Five selected API/CLI/registration tests passed, including actual fixture CLI processes and simultaneous approvals |
| `run-ownership` / `run-ownership-fixed` | Initial run: 114 passed, six failures, one Windows-only skip. Restored the rejected-step rerun guard and required terminal run IDs in existing assertions; affected file plus budget regression then passed all 42 tests. |
| `protocol-final` | Production build, schema drift, lint, import contracts, Vulture, Knip and 27 selected client tests passed |
| `scoped-cli-lifecycle` | 41 tests passed; one opt-in long-wait test skipped and one model test deselected |
| `scoped-cli-cleanup-fixed` | Six cancellation/replacement/stale-socket tests passed. The initial cleanup test read a historical event instead of the current gate; corrected its synchronization, retaining the initial failure log. |
| `scoped-mcp-reconnect` | 42 tests passed, including real SDK/stdio subprocess scope and explicit reconnect. One long-wait skip and one model deselection. |
| `grant-negative-controls` | Fixed tests pass; removing waiter identity, cancellation identity or connection/run ownership makes the corresponding test fail for its intended reason. |
| `shared-invocation` | 70 session/API approval/cancellation and CLI budget tests passed |
| `scoped-invocation-checks` | Lint, schema drift, production build, 27 client tests, import contracts, Vulture and Knip passed |
| `shared-invocation-browser` | Real chat/approval/edit/replay/save/open/manual/export workflow passed |
| `recipe-stop-ownership` | Stop after progress, refusal of another document, completed pixels and autosave recovery passed |
| `updater-protocol-fixed` | Seven Rust loopback tests, Python fixture validation, Rust formatting and maintenance report passed. Initial Rust type-inference/format failures are retained in `updater-protocol`. This is not installed updater acceptance. |
| `grant-scope-final` | Eleven focused tests passed, including core method scope and handshake cleanup; one opt-in long wait skipped |
| `grant-negative-controls-final` | Five fixed tests pass and fail as intended when each recipe Stop / grant / cancellation guard is removed |
| `storage-independent-onboarding` | Normal and storage-disabled first-run browser/core approval/Stop workflows passed |
| `protocol-native-desktop` | Current Linux debug build and development launcher passed private-Xvfb startup, core crash/recovery, clipboard/dialog and close workflows. Not a packaged installer or downloaded updater test. |

The resource reporter's own 5 contract tests passed in `modernization-review`.
Its original 1,000-step/100-turn run failed to save at the 16 MiB metadata limit;
that failure is intentionally retained. After bounded automatic retention the
same workload saves/reopens with exact output bytes and branch/step counts:
compact session JSON **65,929,796 → 6,948,408 bytes**, branches **201 → 11**.
These are bookkeeping measurements on tiny images, not general rendering or UI
performance claims. The saved archive was 226,560 bytes; the measured save/open
times were 0.323/0.466 seconds in that single run.

No live providers, Windows/macOS native workflows, PowerShell runtime test, frozen
core build, or packaged installer acceptance were executed. The Windows quoting
test is present for a Windows host; Linux exercised POSIX. The PyInstaller
fingerprint resource is now verified in a frozen Linux core; installer/platform validation remains open. These gaps mean
W1 is not a fully validated cross-platform release.

## Review and maintenance cost

No dependencies, settings or alternate pixel execution path were added. The new
build-identity helper has two callers: replay keys and the existing packaging spec.
Atomic byte publication replaces direct final-file writes. Log rotation replaces
direct unbounded stderr append; diagnostic tail reading replaces full-file reads.
The history workload extends the existing reporter and uses disposable projects.

Safeguard review: existing pixel, collision, migration and process assertions are
retained. Cache assertions include the new fingerprint; replay's existing archive
regression now covers both codec and build changes. New failure injection proves
publication cleanup and profile-save preservation. No skips, analyzer exceptions,
golden changes or test selection changes were introduced. The maintenance report's
keyword-based safeguard flags were reviewed; they do not represent suppressed tests.

The second-pass review found and addressed overlapping log-reader rotation,
legacy oversized log rotation, failed profile-save ownership, and preservation of
unmarked legacy directions. Residual limits are documented above. No migration to
new image identity, revision membership or storage has been silently substituted.
The invocation review also caught reusable step-label cancellation collisions,
old sockets borrowing new runs, per-call standalone reconnects changing documents,
a core method-scope gap, interrupted welcome grant retention, and revision-strict
recipe Stop. Their focused evidence is listed above.

The API invalid-edit assertion now requires the canonical recorded step result
used by CLI too; rejection and reason assertions remain. Updater test welcomes
use the shared complete contract fixture. The maintenance report is retained at
`updater-protocol-fixed/maintenance.md`: most growth is generated wire types.
Transport/ownership complexity was reviewed as safety logic rather than split
to satisfy a numeric target. No new runtime dependencies were introduced.

## Storage and reconciliation continuation

Upstream `ae4297cab3dd027d969cd74c13560e50763e4a20` is reconciled with the
modernization work. The reconciliation preserves #45 themes, #47 idle-stream
clearing, #46 creation workflows/manual history/HEIF/recipes, and #48–49 release
metadata and Windows smoke changes. The registered contracts now cover those
methods and results. Pattern-constrained recipe input maps generate typed values.
A later fetch advanced to `1b404cfc09e04394d3f451ccd950fce772fe208d` (#50): authenticated draft-release listing and its tests. That change is isolated from storage and is included in the final reconciliation. Nothing was published remotely.

Encoded images now reside in hash-verified disk files. Preview forks own temporary
outputs and independent links to inputs. Failed batches delete their published
files; normal core shutdown explicitly releases session scratch storage. Immutable
publication uses file flushing and POSIX directory synchronization. Windows power-loss
behavior and hard-kill scratch reclamation remain unverified/incomplete.

Local autosave now uses SQLite storage version 1 and persistent immutable blobs.
Metadata nodes share unchanged records and chunked list membership. The writer
publishes blobs before a short transaction, uses DELETE journaling with EXTRA sync,
and stages initial database creation. Startup settles hot rollback journals before
moving the database. A process-death test exercises actual journal rollback.
Legacy recovery ZIPs remain migration inputs and are preserved after restore.
Manual undo/redo and branch snapshots round-trip through the same validators.
Corrupt standalone recovery is preserved separately so fresh work can autosave;
unsettled journals and unsupported storage versions are never silently discarded.

Collection retains both current and previous recovery, waits 24 hours before
removing unreachable blobs, and refuses collection if any recovery metadata is
unreadable. Metadata garbage is removed transactionally. Periodic collection is
bounded to once per hour for the active recovery folder. Portable schema 4 saves
remain ZIP archives and retain their size/hash/decoder/reference safeguards.

### Evidence and review

- `reconcile-browser`: all 10 upstream creation/history/recipe workflows passed.
- `disk-blobs`: frontend build passed; initial storage failures exposed implicit
  temporary-directory cleanup, which was replaced with explicit lifetime cleanup.
- `recovery-storage`: 194 focused tests and lint passed.
- `storage-quick`: 1,487 core tests passed, 8 failed, 51 skipped; 84 frontend tests
  passed, 1 failed; all 13 Rust tests, formatting, build and workflow tests passed.
  This run is not reported as an overall pass.
- `storage-followup`: stale-source evidence only; synchronization was refused while
  the quick harness held the checkout. It does not validate subsequent fixes.
- `storage-followup-fixed`: 73 core tests passed; three remaining provider assertions
  needed terminal run identity. Settings controls passed. The privacy test passed
  serially; its initial parallel timeout occurred before the owned request arrived.
- `storage-final`: 181 tests passed, including corrected provider protocol assertions,
  portable project round-trip, manual history, previews, cleanup and recovery failure
  injection. Lint, generated contracts, import boundaries and Vulture passed.
- `sqlite-browser`: all 10 real recovery/reconnect/recipe scenarios passed, including
  killing the core, matching recovered bytes, saving/reopening and preserving drafts.
- `sqlite-desktop`: debug build and development-launcher native workflow passed.
  The direct debug native run failed at GTK Open acceptance; retain that failure.
  `storage-review` initially reran a debug binary overwritten by the development
  launcher, so it pointed at a stopped Vite server. After rebuilding,
  `storage-native-final` passed actual native recovery/clipboard/Save/Open/close.
  Do not equate these source runs with installer validation.
- `storage-benchmark` and `storage-benchmark-optimized`: same deterministic
  100/200/500/1,000-step workload, 11 retained branches, exact state/pixel round-trip.
  At 1,000 steps, initial recovery commit/open were 6.88/6.48 seconds. Grouping
  small records and caching reads reduced them to 0.33/0.61 seconds; comparable
  archive save was 0.35 seconds. SQLite metadata was 1.28 MB versus 6.73 MB expanded
  JSON. This is a small-image workload, not a large-media memory benchmark.

The second-pass review caught hot-journal rename risk, implicit scratch cleanup,
corrupt existing nodes being accepted by INSERT OR IGNORE, missing aggregate
recovery size checks, and metadata fragmentation. Focused regressions preserve
those guards. Updated path assertions now name SQLite recovery, and event assertions
require run identity as well as their previous payloads. The media staging test
allows only the session's owned blob directory while live and requires it to be
gone after shutdown. No pixel goldens were changed by this storage work; upstream
creation-workflow golden changes were preserved during reconciliation.

- `storage-review`: 138 project/recovery tests passed, including size guards and
  corrupt-recovery preservation. Maintenance initially lacked its optional quality
  environment and an upstream ref in the private clone. `storage-maintenance`
  passed all 10 maintenance tests; `storage-native-final` reports growth against
  the fetched upstream commit after importing its bundle into a task-specific ref.
- `storage-frozen`: freezing caught the prior fingerprint spec's invalid `WORKPATH`
  name. The documented PyInstaller global is `workpath`; after that fix,
  `storage-frozen-fixed` built the onedir core and passed normal-exit and forced-death
  smokes, bundled HEIC/PDF/video, SQLite recovery bytes and worker cleanup. The
  packaged fingerprint matches the current core source. `runtime.json` records
  SQLite 3.53.1, compile options and the storage version/journal/sync policy.

- `modernization-integrated-core`: final shared-storage regression run passed
  1,498 core tests; 51 platform/opt-in checks were skipped. The changed generator
  nullability/pattern-property regression passed. No full-suite failure is hidden
  by the earlier focused reruns.

### Remaining at the storage checkpoint (superseded by the continuation below)

The full W0–W14 modernization is **not complete**. W4 explicit artifact-use,
invocation and named-output identities remain open. W5 now shares branch/undo
records in memory and schema-5 archives, but still materializes the active timeline.
W6 still needs durable command intents,
receipts, commit-before-event semantics, inspection/repair UI and migration/rollback
release coverage. The current session remains the mutation authority.

Also outstanding: the remaining resource/media scheduling and binary delivery,
normalized UI projection and chat/gallery windowing, provider-neutral bounded conversation model,
remaining accessibility work, scratch/cache budgets, full resource baselines,
packaged cross-platform release gates and user rollout/study work. The plan's
100 ms commit proposal is met by one small-image 1,000-step sample, not an established p95 budget. No live provider,
macOS/Windows native release, signed update or installer outcome is claimed.

## Shared history and schema-5 migration

Branch and manual-undo heads now reference SHA-256-addressed immutable records.
List membership uses chunks of 32 references rather than a full copied timeline
per checkpoint. Activation materializes independent models; collection retains
all branch and manual-history roots. Failed/no-op manual edits remove speculative
records. Normal UI snapshots exclude inactive branch history and the node graph.
Source-credit traversal uses the same branch-state reader.

Schema 1–4 archives migrate through the existing parameter, ID, transcript,
reference, image and archive-bound validators. Overwriting a legacy archive first
publishes a verified byte-identical `.pre-v5.badshop` sibling without replacing
existing backups. Failed backup publication prevents archive replacement. Current
portable saves use schema 5; older releases need the retained pre-v5 copy.

Verification to date: `history-migration-reviewed` passed 187 focused tests and
lint; `history-frontend` passed the production build and five document-replacement
checks after installing the isolated worktree's missing Node dependencies. The
initial browser run passed branch/save/reopen but exposed the missed source-credit
caller during export. After fixing that caller, all six project journeys passed
in `20261114T063513Z-320835`, including actual export bytes and reopen.

The same 1,000-step / 11-branch small-image workload now has 1.49 MB document JSON
(previously 6.73 MB), 86 ms recovery commits (previously 330 ms), and 108 ms portable
saves (previously 350 ms). Recovery database size increased from 1.28 to 2.67 MB,
and reopen increased from 610 ms to 1.39 seconds. This is a measured tradeoff, not
a blanket performance improvement. Raw measurements are in `history-benchmark`.

## Pane recovery, long histories and CI reconciliation

Independent render boundaries keep the other panes and header available after a
pane render failure. Retry remounts only that pane. Chat drafts live in the existing
UI store and survive pane remounts; document replacement clears them. Late send
responses cannot clear a replacement document's draft. This is not a claim that
every form or attachment survives a whole-workspace failure.

Histories above 100 steps now use variable-height windowing with stable step keys,
overscan and full-history Arrow/Home/End navigation. Selection remains mounted for
focus continuity. The real-core 250-step browser regression checks bounded mounted
rows, keyboard focus/scrolling and an unchanged persisted timeline. The existing
timeline remains the owner. `@tanstack/react-virtual` 3.14.26 is the one added
runtime dependency; it supplies variable measurement/scroll reconciliation instead
of a second custom layout engine. Production gzip JS grew from 306.86 to 319.47 KB.

CI exposed three regressions: a stale-command rejection needed snapshot refresh
without replaying the rejected mutation; onboarding's mocked download events lacked
the required protocol ownership envelope; Quick ideas retained an old literal
artifact and raced automatic against explicit replay. Quick ideas now selects the
step output and opts out of automatic replay when it owns the explicit replay.
The browser assertions remain unchanged. No pixel goldens or skips were added.

Evidence:
- `20261114T062616Z-296618`: 1,503 core checks passed, 51 skipped; 85 frontend and
  13 Rust checks passed, with build/lint/format/workflow checks. This predates the
  pane/windowing and CI follow-up changes.
- `panel-isolation`: 11 component checks, types and nine release-gate tests passed.
- `20261114T063513Z-320835`: all seven project/long-history browser journeys passed.
- `history-panel-final`: 36 focused history checks, all 87 frontend checks,
  production build, strict Knip and Ruff passed.
- `history-negative-control`: removing the expanded-history size guard makes its
  focused test fail for the missing exception; the probe detected that failure.
- `ci-followup`: 13 replay-ownership and eight conflict/draft checks, types and
  generated contract checks passed.
- `20261114T064202Z-323686`: 25 browser checks passed; enlarged-text export failed
  after a connection loss. Serial `20261114T064708Z-329054` passed both quick-share
  journeys. A bounded connection-end diagnostic now records the reason if repeated.
- `history-depth-review.log`: seven migration checks passed after the second-pass
  review also made shared-subtree depth validation independent of traversal order.

Upstream #51 and #52 are merged, including 0.5.3 candidate acceptance isolation.
The last upstream check remains `6fef86133a944e09ef2406c0af2408c745ffdd14`.
PR #54 is the integration review; its existence does not close the remaining ledger.

Current-head validation at `9eb8caa`: GitHub core CI passed 1,525 tests, with 56
skipped and one deselected. Private-Xvfb `20261114T065043Z-330168` passed the debug
build, native recovery/clipboard/Save/Open/close and development-launcher workflow.
The full browser CI passed 111 journeys and failed Y2K selected-row contrast: the
new `aria-pressed` state matched a generic glossy-button rule. The fix includes
timeline rows in the existing readable selection rule. All 11 theme workflows
passed in `20261114T065813Z-346304`, retaining contrast and byte-identity assertions.

The long-history regression additionally scrolls before making any selection and
enters the timeline using Tab. It failed because no mounted row remained tabbable
(`20261114T070622Z-349191`). Keeping the first row as the initial roving Tab stop
fixed the failure; the same test passed (`20261114T070729Z-349733`) with bounded
mounted rows, full keyboard navigation and all 250 core steps preserved.

## Schema 6 / operation / context completion continuation

Task baseline and fetched upstream: `105f37e73abfe7067868e392dd2b669a825f7b58`.
This includes the merged #54 history work and upstream #53/#55/#56 installed
acceptance, Flatpak and release/licence work. No release tag is created by this task.
The Windows implementation worktree is `architecture-audit/BadShop`, branch
`codex/modernization-completion`; Linux verification uses the isolated
`badshop-linux-test/worktrees/architecture-completion` checkout and its own venv.

### Implemented ownership and acceptance

- W2/W3/W6: document commands have durable pending/committed receipts; retries
  retain the same operation identity and never repeat a pending side effect.
  Document events follow a successful commit. Running steps commit before worker
  execution. Disk-full admission fails without executing; interrupted runs recover
  as errors. Steps retain parent operation IDs and recipe row/item positions.
  Receipt inspection links retained invocations; oversized/evicted cached replies
  retain deduplication tombstones. Chat acceptance and terminal run completion
  remain distinct. No exactly-once external-file claim is made.
- W4: immutable logical artifact uses share byte hashes, with distinct provenance
  for identical imports and outputs. Named producer/output bindings replace
  positional replay substitution. Missing ports fail explicitly. Unknown tools
  open read-only; structurally invalid documents are still refused. Schema 1–5
  migration preserves existing ambiguity, and schema 6 save preserves a verified
  pre-v6 archive. Recovery storage 1 upgrades with a verified, exclusive pre-v2
  backup, including when an older/damaged backup already occupies its name.
- W5: shared branch/undo records remain authoritative; temporary history leases
  protect a manual transaction's undo snapshot during running-step commits.
  The current timeline is deliberately materialized for editing. There is no
  second live event-sourced document or alternate mutation executor.
- W6/W11: storage inspection checks recovery and library integrity without
  overwriting evidence. Healthy library entries remain available when another
  entry is corrupt. Shared-library blob collection uses a one-day grace period
  and refuses collection on unreadable metadata. UI library pages bound mounted
  cards and thumbnail requests; full collection exports gather all entries.
- W7: worker writes/partial reads have idle and absolute watchdogs; encoded inputs
  and IPC frames have explicit ceilings. Media decode admission is separate from
  document mutation locking. Authenticated WebSocket binary replies replace the
  renderer's base64 transport; no file-serving HTTP endpoint is introduced.
  Core/renderer view caches have byte ceilings, and Blob URL effects own cleanup.
  Aged scratch reclamation requires a marker and proof its process is dead.
- W8: a normalized projection supplies step/output lookup, live text has its own
  store, completed Markdown is memoized, and long chat/gallery/timeline views are
  windowed with keyboard navigation. Saved-library views use 50-entry pages.
- W9: canonical conversation records replace persisted OpenAI envelopes. Request
  projection retains complete bounded turns and images; continuation metadata is
  scoped to adapter/model/document/branch/version. Measured request bytes, timing,
  reported usage and omitted turns are visible; unknown costs are not invented.
  Local one-edit/face-selection policy moved from HTTP transport into the agent
  layer; face geometry follows the recorded invocation, independent of prose.
- W10/W12/W13: existing pane isolation, close/recovery ownership, release receipt,
  package identity and promotion gates are retained. The supplied scope is one
  coordinated migration PR as explicitly requested, superseding the normal
  one-behavior-per-PR preference. No engine pixel algorithm or pixel golden changes.
- W14: current architecture/compatibility guides describe the actual new owners,
  bounds, schema migration, backup and rollback limitations. Legacy format readers
  and protocol-1 JSON media name their supported clients and removal conditions.

### Decisions and gates that are not implementation passes

The original plan contains experiments and external acceptance work as well as
code. ACP adoption, shared-memory IPC, immutable active-timeline storage, portal
permission reduction and installer payload pruning are not automatically better
architectures. The current explicit owners and bounded paths remain; adoption of
those alternatives requires the plan's comparative measurements and compatibility
exit criteria. No unverified alternate runtime is enabled merely to check a box.

Live provider authentication/actual image and continuation behavior, installed
Windows/macOS acceptance, signed update/rollback, native screen-reader observation,
publisher signing/notarization and consenting beta-user return studies are separate
release/field gates. Fixture tests and a source Linux debug build cannot satisfy
those gates. No invitations, credential provisioning, paid model calls, signing
identity setup or public release publication are implied by this implementation.
The full original W0–W14 acceptance remains open wherever such evidence is absent.

### Verification in this continuation

Evidence is retained under the Linux worktree's `artifacts/verification/`:

- `20261114T155231Z-1944`: 101 receipt, history, worker, library, identity and real
  WebSocket checks passed; one model test deselected.
- `stream-component.log`: 30 stream/document-replacement/RPC component checks passed.
- `20261114T160230Z-5665`: 50 receipt/migration and recipe/layout checks passed.
- `20261114T160250Z-5787`: broad run found two core expectation/commit failures,
  one protocol fixture failure and a missing snapshot field; not a passing run.
- `20261114T160629Z-21447`: 119 passed, one canonical invocation-link expectation
  failed and was corrected without removing content or pixel assertions.
- `20261114T161103Z-778`: 1,533 core checks passed, two failed; 92 frontend checks
  passed. Lint and frontend fixture compilation still required corrections.
- `20261114T161524Z-657`: all 12 focused privacy/local-strategy/protocol/agent checks
  passed after those fixes. Cold SDK import is outside the five-second active-request
  cancellation bound; no cancellation assertion or timeout was weakened.

Final browser/native, resource measurement, maintenance, negative control, frozen
smoke and PR CI outcomes are recorded below after they run. Earlier passing runs
are not represented as validation of edits made afterward.

The user explicitly retained paid/live-model testing on 2026-11-14. It is excluded
from this implementation PR, rather than represented as fixture-verified compatibility.


### Upstream reconciliation and second-pass review

Fetched main advanced from `105f37e` to `b4f6fcccea37f3a9ebc5a536069daf89a0b7e245`:
#57 adds onboarding/compact workflows; #36 adds fuzz/mutation coverage. The merge
preserves compact-view navigation with invocation/output selection, Settings tab
selection with storage restoration, and scripted-provider availability alongside
usage and read-only snapshot fields. Wire contracts were regenerated.

The new fuzz test uses one real saved archive per test session: random artifact
identities otherwise changed compressed size between Hypothesis replays. It still
mutates archive bytes, checks clean refusal or exact saved state/pixels, and verifies
that the original stays unchanged. Restored artifact stores close explicitly.

The separate review traced changed entry points and found concrete regressions:
concurrent media responses could over-admit cache bytes before query settlement;
terminal events preceded the final durable revision; corrupt previous-launch
receipts blocked fresh owned documents; and raw filesystem failures could omit a
terminal outcome. Focused regressions cover byte admission/URL cleanup, persisted
assistant content followed by an owned edit, preserved corrupt evidence with
stale/legacy refusal and duplicate receipt reuse, and terminal error/run release.
The active receipt store always fails closed. Old-context requests cannot bypass
an unreadable previous store. Local face-edit policy now resolves geometry through
the recorded invocation rather than parsing result prose.

Final Linux verification moved to the isolated
`badshop-linux-test/worktrees/architecture-completion-final` checkout. The older
`20261114T162817Z-722` run is invalid environment evidence: dependencies disappeared;
subsequently WSL was unavailable during user disk maintenance. It is not reported
as a passing check or an application regression. The fresh checkout has a separate
verified editable environment and retains the exact transferred-file manifest.

- `20261114T163622Z-991`: 15 focused checks passed; the newly merged fuzz strategy
  failed due to changing archive lengths. The fixed fixture passed in the full run.
- `focused-frontend.log`: nine media/Settings/chat component checks and build passed.
- `20261114T163742Z-733`: 1,545 core tests passed, 51 platform/opt-in skips;
  94 frontend and 13 Rust tests passed, plus workflow checks, Ruff, Rust format and
  production build. Gzipped frontend JavaScript is 324.47 KB. This predates the two
  final storage-error review fixes; their follow-up is below.
- `20261114T164557Z-770`: all ten receipt tests passed, including both review fixes.
- `completion-ownership-probe`: the document-ownership test passed with the guard
  and failed with the expected missing exception when the guard was removed.
- `completion-negative-controls`: recovery isolation and concurrent media admission
  each passed normally and failed the intended assertion with its guard removed.
  Temporary mutations were restored and checked before further verification.


The final W9 follow-up replaces optional provider context flags with an immutable
`ContextPolicy` on the provider contract. Real adapters and scripted test adapters
use the same safe defaults; local strategy requests full IDs and Perplexity opts
into scoped continuation metadata. SDK failures carry safe typed categories and
retry advice; authentication/permission/context/request failures do not offer
continuation, while transient timeout/connection/rate-limit advice can. No raw
SDK error body is exposed. Unknown adapters retain the existing explicit unknown
category; no live support claim is inferred from a fixture.

- `20261114T164632Z-1254`: full browser run passed 113, skipped one, and failed one
  material-reuse test's assumed artifact count. The test now checks the new use
  directly and retains equal-byte identity, composition inputs and reopen checks.
- `20261114T165717Z-748`: 160 provider/agent/receipt checks passed; one test double
  shadowed the new provider base name. `20261114T165812Z-1853` passed all 11 checks
  in that file after renaming it. One opt-in engine-model journey was deselected.
- `provider-advice-ui-final.log`: 12 component checks passed, including retry advice.
