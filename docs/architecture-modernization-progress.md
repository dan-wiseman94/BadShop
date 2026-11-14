# Architecture modernization implementation status

Implementation baseline: `fb1ad675546bd466d5578fbf324a72361458a619`.
The five audit documents were inherited task material, retained in checkpoint `2f8316c`. The full W0–W14
plan remains authorized; this ledger does not mark it complete.

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

### Remaining

The full W0–W14 modernization is **not complete**. Disk-backed images and shared
recovery metadata do not finish the document migration: W4 explicit artifact-use,
invocation and named-output identities, W5 shared in-memory revisions, and the
portable-format migration remain open. W6 still needs durable command intents,
receipts, commit-before-event semantics, inspection/repair UI and migration/rollback
release coverage. The current session remains the mutation authority.

Also outstanding: the remaining resource/media scheduling and binary delivery,
normalized/windowed UI projection, provider-neutral bounded conversation model,
render boundaries/accessibility, scratch/cache budgets, full resource baselines,
packaged cross-platform release gates and user rollout/study work. The plan's
100 ms commit proposal is not met by the 1,000-step benchmark. No live provider,
macOS/Windows native release, signed update or installer outcome is claimed.
