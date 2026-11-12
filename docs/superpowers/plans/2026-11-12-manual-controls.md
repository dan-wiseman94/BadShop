# Manual correction controls

Requested scope: implement all ten controls discussed on November 12.
Baseline: clean HEAD and fetched origin/main c0d9ae700c4f413b43a807d4b58e353405805541.

## Acceptance

- Placement: select a paste step, drag/resize/rotate/flip and nudge with arrows
  (Shift = ten pixels); replay updates dependent images.
- Captions: edit exact wording, line breaks, size and placement; fitting must
  preserve wording and report overflow when it cannot fit.
- Replacement: replace a source while preserving destination transforms and
  preview the crop before committing.
- Preview: parameter changes render without changing history, artifacts or dirty
  state; Apply commits through session execution; Cancel discards the preview.
- Locks: independently protect source, wording and placement during later AI work;
  conflicts are enforced by the core, including CLI/MCP calls, and remain visible.
- Effects: inspect and bypass supported effects, replaying dependent output from
  the original inputs rather than compounding previous previews.
- Variations: compare bounded alternatives for one parameter, with fixed other
  parameters and explicit seeds; only the chosen alternative is committed.
- Cutouts: preview hard alpha against contrasting backgrounds and adjust crop,
  threshold, grow, oval and outline using existing tool parameters.
- Pause: stop at an operation boundary, allow edits, resume with updated agent
  context; support a checkpoint before finishing effects.
- Undo: restore the state before the last AI turn while preserving the attempt
  as a branch, including chat and creative preferences.
- Committed controls survive save/reopen. Errors preserve prior work. Temporary
  preview work and owned processes are cleaned up on cancel/disconnect.

## Ownership and verification

Reuse Viewer/ToolForm/Timeline for interactions, the tool registry for parameter
validation, Session for execution/replay, and existing branches for recovery.
Do not add a second pixel engine or let the UI own persistent domain state.

Start with focused session boundary tests and one real browser/core journey for
each independent workflow, checking pixels and project reopening. Use isolated
Arch WSL and private Xvfb for native keyboard/drag verification. Retain evidence
under artifacts/verification. Review concurrency, dependency remapping, older
project formats and lock enforcement separately before handoff.

## Working status

Implemented placement/nudge/resize/rotate/flip, exact caption fitting, source
replacement, before/after previews, parameter pins, effect bypass, three-choice
variants, cutout backgrounds, pause/finish checkpoints and recoverable turn undo.
The viewer also exposes manual transform, text, arrows/shapes and censor tools.
See `docs/manual-controls.md` for behavior and limits. Pins require review of
downstream operations; they do not recognize or protect arbitrary pixel regions.

Focused Linux core runs passed: 270 tests covering registry/schema/project/server
integration, 99 covering session/agent/server/branches/compatibility, and 29
covering exact caption fitting and existing text behavior. After the final review
fixes, seven preview/geometry/checkpoint/bypass tests passed again. Real browser/core
journeys verified preview cancellation, byte equality after apply, stale-preview
removal, bypass persistence, replacement preserving placement, nudge and variants.
The existing project editing/reopen/export journey also passed.

TypeScript, Ruff, import contracts, high-confidence Vulture and strict Knip passed.
The growth report uses the task baseline commit because the isolated Linux bare
repo has no origin/main ref. Approximately 500 production lines implement the
controls with no new dependency or process. Approval-dependency negative control
passed: working source passes, removing the guard fails the same regression.
Independent review findings were fixed and covered by focused regressions.

Linux source desktop build and private-Xvfb native smoke passed: authenticated
renderer, clipboard import, core-crash recovery and guarded close/cleanup. The
combined desktop command ended before recording its launcher check; a separate
launcher retry passed. Placement-specific keyboard interaction was exercised in
Chromium, not the native WebKit renderer. Installers and other OSes were not tested.

Evidence is retained under `artifacts/verification`: runs 20261112T224242Z-785,
20261112T224804Z-731, 20261112T225452Z-642, 20261112T224714Z-742,
20261112T230259Z-740, 20261112T230324Z-1460, 20261112T225535Z-644,
plus final-maintenance and guard-probes. Failed interim runs remain retained.

Remote main advanced from c0d9ae7 to 01e6f0c7b356c28157015dccec75a7bf2d91e254.
Reviewed intervening changes: release/update work has no implementation overlap.
The newer generated-wire-types migration overlaps app/src/types.ts and widens
Viewer.faceBoxes nullability. At integration, retain that migration and regenerate
wire types from the new Step model so bypass/pin fields remain schema-owned.
This worktree remains based on the recorded task baseline; upstream is not merged.
