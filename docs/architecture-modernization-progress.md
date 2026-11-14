# Architecture modernization implementation status

Implementation baseline: `fb1ad675546bd466d5578fbf324a72361458a619`.
The five audit documents are inherited uncommitted task material. The full W0–W14
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
fingerprint resource requires packaged validation before release. These gaps mean
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

## Concurrent main changes

Latest fetched `origin/main`: `ae4297cab3dd027d969cd74c13560e50763e4a20`.
This continuation started at remote tip `0df3ba2fb66bd61e204199942dd4cc1e6b5da1d6`.
The theme/XP change (#45) is separate from the runtime changes. PR #47's idle
snapshot stream clearing is included in this task's reconciliation logic; retain
its upstream controller regression on integration.

Main advanced again with #46 (creation/reusable editing workflows). Its overlap
is material: new project-recent/history/media methods, manual undo/redo snapshots,
HEIF artifacts, recipe inputs/row results, branch/history mutation wrappers,
settings records, native capture capabilities and additional packaging resources.
Before integration, add those registered results/scopes to the contract registry,
regenerate types from the merged models/signatures, preserve the upstream UI and
engine features, and rerun their affected workflows. W4–W6 must migrate manual
undo/redo membership as well as automatic turn checkpoints. Neither main change
has been merged or overwritten in this task worktree. No remote publication or
commit was performed.
The subsequent #48 release preparation changes version/lock metadata to 0.5.0
and adds readiness waits to two upstream browser tests. Preserve those when
reconciling the recorded #46 overlap; they are not incorporated here.
The last fetch also includes #49: version/locks advance to 0.5.1 and the Windows
editing smoke explicitly chooses files in the new Add material dialog. It is
reviewed and remains part of the pending upstream reconciliation.

## Remaining

The full modernization is **not complete**. W0 needs the remaining media/library,
renderer and target-hardware baselines. W2 still needs durable operation receipts
and removal of transitional context-free clients. W3 still needs full parent
invocation/recipe lifecycle, deadline and resource policy. W4, structural sharing in W5, W6–W11,
remaining W12/W13 work and W14 rollout remain open. Explicit artifact-use/output
identities, transactional SQLite/disk-blob persistence, resource scheduling,
normalized UI, provider-neutral context, accessibility, provenance/GC and release
rollout have not been implemented. Continue from the detailed plan.
