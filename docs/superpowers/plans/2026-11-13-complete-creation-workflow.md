# Complete creation workflow

User authorized all ten proposed improvements. Baseline: a090351; no inherited edits.
Status: all ten feature implementations and focused acceptance journeys are complete.
Final frozen-core capture validation passed. This is source development,
not an installer release. The entries below are a chronological work log; later
results supersede earlier statements of remaining work.

## Final acceptance audit

PR integration follow-up: PR #46 was rebased onto fb1ad67. Initial CI exposed
missing animation/parameter inventory coverage and stale workflow expectations.
Expanded CLI round-trip samples reproduced three real defects: nested frame and
polygon values lacked JSON serialization, and focal coordinates parsed as ints.
The existing schema-driven CLI now handles these values. Golden changes add only
selection metadata and a new animation case; every prior pixel/encoded-byte hash
is unchanged. Browser fixes retain the actual pixel/state assertions, wait for
replay completion and use the new import/named-row controls. The unchanged 900x600
coordinate test reproduced a squeezed canvas; scrollable toolbar controls and
temporarily hidden material panels during picking restore usable Fit geometry.
Focused verification: 162 core/contract/golden checks passed; one accidental text
encoding change was corrected and its golden rerun passed. All seven failing
browser journeys now pass (six in pr46-browser-fixes, recipe in
pr46-cast-recipe-fixed). Ruff and TypeScript passed. Evidence is in the isolated
`complete-creation-pr` Linux worktree; failed runs remain retained.

All evidence directories below are under `artifacts/verification/` in the isolated
Arch worktree `/home/dan/.local/share/badshop-linux-test/worktrees/complete-creation-workflow`.

| User workflow | Acceptance evidence |
| --- | --- |
| Find and reuse material, assign roles and fill layouts | material-workspace browser journeys; session artifacts remain the owner |
| Select recorded paste/text/layout elements and preview dependent results | recorded-element-pixels (8), recorded-elements-replay (1), recorded-element-boundaries (2); immutable preview, exact replay/reopened bytes |
| Repair a cutout with keep/remove polygons | cutout-repair core and creation-journeys-corrected browser; binary alpha, original RGB, matching preview/output and reopen |
| Set exact text, frames and panel focal points | text-panel-core (44), text-panel-browser (2), portable-caption-hard-masks; explicit overflow and hard glyph edges |
| Prepare and save bounded exports, presets and animations | export-presets-browser, export-multiple-sizes, animated-export-browser; actual encoded dimensions, sizes, timings and saved bytes |
| Import phone photos, pictures, clips and pages in one place | heic-worker-synced (3), heic-browser (1), bundled-pdf-core (3), bundled-pdf-browser-complete (1), bundled-video-core (6), media-upload-core (1), add-material-browser (1); cancelled pending pages retain completed imports |
| Undo manual changes and find/recover projects | manual-history-corrected, manual-history-boundaries, project-home, project-home-browser, project-home-recovery; real pixels, persisted history and external-file retention |
| Save a reusable design and run/retry named rows | named-designs-browser (3), named-designs-final (5); distinct image roles, cross-project persistence, completed output retention |
| Edit a short GIF | animation-edit-final-core (6), animation-frame-thumbnail (1), animation-edit-complete-journey (1); frame pixels/timings, preview/cancel, undo/redo, replay and reopen |
| Capture a region and annotate it | capture-region-core (3), capture-region-browser (1), capture-portal-cleanup (3), capture-native; crop-only persistence, cancellation, real private-display capture, window hide/restore and clean close |

Boundaries: Linux X11 native capture is exercised on private Xvfb. The Wayland
portal tests use a real private D-Bus with a fixture portal, not KDE's permission
dialog. Windows/macOS native capture and installed packages have not been tested.
The direct-link UI reuses acquisition; no new live network/provider test was run.
Portable bundled text supports Latin-1; unsupported text fails explicitly. Element
selection stops at unknown geometry. Documented file/frame/pixel/row budgets apply.

## Final review and maintenance

Reviewed the normal UI/RPC paths separately from implementation using
`docs/diff-review.md`, including history snapshots and archive references, recipe
role resolution/cancellation, preview ownership and capture cleanup. A concrete
finding in `session/media.py` was fixed: cropping a screenshot previously reused
the document-crop path and embedded the full desktop as an original. Captures now
import only selected pixels. `capture-region-negative` runs the same real worker
test against a temporary copy with that guard removed: fixed code passes; former
behavior fails on two retained artifacts instead of one. No other actionable
finding was established in this pass.

All three import contracts, Ruff, high-confidence Vulture, strict Knip and
TypeScript passed under `workflow-final-maintenance`. Knip's two existing
configuration hints remain advisory. The first growth-report attempt failed
because the Linux mirror has no origin/main ref; `growth-baseline.log` succeeds
against recorded task baseline a090351. Growth is +1411 production lines across
the ten workflows. The larger caption/media/recipe branches implement requested
rendering, codec and role cases in their existing owners; no new execution queue,
provider pixel path or duplicate project store was introduced.

Maintenance cost: pillow-heif handles phone photos, pypdfium2 renders PDF pages,
PyAV replaces external ffmpeg/ffprobe extraction, and Linux-only dbus-fast handles
the screenshot permission portal. All are locked and collected in frozen builds.
The old missing-codec UI and subprocess paths are removed. New UI components own
the requested import, project, animation and repair controls; capture.py isolates
the OS boundary. No new background process runs outside existing worker ownership.
Recipe v1 and optional schema-4 history remain compatible with persisted files;
their removal requires a deliberate persisted-format migration.

Safeguard changes: phone-format rejection became actual HEIF support plus malformed
input refusal. Optional PDF/video skips became real bundled-decoder tests; stalled
decoder injection still verifies actual worker death and source-copy cleanup.
Capture-only opt-in skips protect the user's desktop and were explicitly enabled
on private displays/buses. Protocol expectations add deliberate user-only methods.
Crash recovery now enters through Project home while retaining state/byte checks.
Native readiness mocks disable only the new opt-in probe; existing failure and
stale-completion assertions remain. Other flagged assertion diffs add cases rather
than remove existing failure coverage. No golden pixels were changed to pass tests.

Final upstream fetch: fb1ad675546bd466d5578fbf324a72361458a619, unchanged since the
overlap review below. No upstream integration, commit, push or release was made.

Final packaging evidence: `capture-frozen` built the Linux frozen core and passed
both normal EOF and forced-death smoke runs. Each exercised screenshot decoding,
region-only import/preview disposal, HEIC original-byte persistence, PDF page
render/crop and video frame extraction after source deletion, guarded save/open,
and absence of orphan workers. `capture-native` independently passed the source
debug desktop's real hide/capture/restore, decoded pixels, authenticated catalog,
rendered window and clean close. Its screenshot was visually inspected. These
are a frozen-core directory and a source desktop, not an installed release.

### Current progress

First export slice adds custom dimensions (1–2000 px per side), fit/crop/stretch,
opaque background color, and KB/MB budget entry. Existing preset defaults remain
compatible. This does not yet implement animation preservation, automatic dimension
reduction, saved presets or combined prepare/save.

Verification in the isolated Arch worktree: 3 focused Python checks passed
(custom encoded dimensions/matte pixels, paired dimension validation, hard alpha).
The 2 existing quick-share browser journeys passed (creation/revision/copy/export
and enlarged text/keyboard layout); they do not exercise the new custom controls.
Evidence: artifacts/verification/export-dimensions and export-browser in
/home/dan/.local/share/badshop-linux-test/worktrees/complete-creation-workflow.
Remote main remained a090351 at the last fetch. Changes remain uncommitted.

Follow-up: export now supports explicit animation preservation (GIF frames, per-frame
durations and loop count), bounded total animated pixels/frames, and opt-in dimension
reduction to meet byte limits. Five focused checks passed under export-animation.
Cutout parameters now accept bounded keep/remove polygons in original coordinates,
with a visual polygon selector in CorrectionControls and a Manual tools entry.
Two engine checks passed under cutout-repair; TypeScript compilation passed.
These features still need dedicated browser/persistence journeys and independent
diff review. The shared Output duration type now permits per-frame durations and
has a loop field; verify affected animation contracts before completion.
Next: finish and test export UI, validate cutout repair through real session save/reopen,
then continue the remaining unchecked workflow items. No item is yet marked complete.

Browser follow-up: combined Prepare and save now exports the newly prepared artifact.
Two dedicated real-core journeys passed in creation-journeys-corrected: custom
240x160 PNG export under a 50 KB limit with encoded dimensions/hash and unchanged
source checked; polygon repair with mutation-free preview, matching committed bytes,
save/reopen and replay. The prior creation-first-journeys failures were test setup
errors (missing Quick idea selection and an incorrect steps.edit return assumption),
retained separately. Export saved presets and animation UI journeys remain pending.

Next implementation owners inspected: Viewer already owns an artifact strip; extend
that strip into the material tray rather than add another one. ManualTools supplies
the shared ToolForm. QuickStart saved takes are text-only but branches.list already
returns preview_id. Recipes capture currently rewrites every image ref to $input;
named inputs must preserve distinct image roles. Manual undo should reuse branch
snapshots but must cover transaction boundaries and document ownership.

## Acceptance and owners

### Implemented follow-up slices (full acceptance audit still pending)

Custom export now includes saved settings, multi-size preparation, actual encoded size,
animation preservation and prepare/save. Materials support role assignment, library
reuse and layout drops. Cutout repair, final-dependent previews, exact text, layout
focal points, manual undo/redo, project home, and named design rows have focused
core/browser evidence retained in the isolated Linux worktree. Relevant run directories
include export-presets-browser, export-multiple-sizes, animated-export-browser,
manual-history-corrected, manual-history-boundaries, project-home, project-home-browser,
project-home-recovery, named-designs-browser and named-designs-final. These are source
checks, not installed-release verification.

Current slice: render-time paste/text bounds and layout slots enable canvas selection
through existing step controls. Composition ancestry retains coordinates; unknown
transforms stop overlays rather than invent hit areas. Selection does not mutate the
project, and the final canvas follows its output slot through replay. Pixel parity
passed 8 checks under recorded-element-pixels. The real canvas selection/edit/preview/
replay/reopen journey passed under recorded-elements-replay; two selection/geometry
boundary checks passed under recorded-element-boundaries. TypeScript, changed-engine
Ruff and git diff --check passed. Earlier failed browser attempts are retained: one
missed workspace onboarding, one checked output before dependent replay completed.
The final assertion waits for done status and compares exact preview/output bytes.
Fetched origin/main remains a090351.

Remaining: unified intake/HEIC and decoder setup, native region capture and
annotation, then final acceptance/maintenance/diff review. All ten original requirements
remain in scope. No feature is declared complete solely from a partial slice.

GIF implementation: animation_edit is a normal deterministic tool with explicit frame
order/duration, crop, speed, loop override and caption output ranges. The visual strip
supports trim, reorder, duplicate/delete, reverse, ping-pong and holds. New-tool preview
reuses packs_api's existing tools.preview with revision checks. The selected animated
original stays visible in ImagePicker; frame thumbnails use artifacts.frame max_px.
Six engine tests pass (animation-edit-final-core), and the frame editing/preview/cancel/
save/replay browser journey passed (animation-edit-original-picker). Expanded browser
coverage for crop/caption pixels and undo/redo passed under animation-edit-complete-journey.
The test decodes real GIF bytes to assert 60x40 dimensions, [500,40,500] ms timing and
caption presence only in its requested frames; source bytes remain identical. Save,
reopen, undo/redo and replay retain exact output bytes. The frame-thumbnail pixel check
passed under animation-frame-thumbnail. Current TypeScript, Ruff and git diff --check
passed; origin/main was fetched and remains a090351. Failed iterations are
retained: duplicate preview registration removed, speed numeric step corrected, and
the animated-original picker omission reproduced and fixed. No source data was lost.

Text/panels: new manual captions use a bundled Latin-1 Aileron option (no system lookup
or download); local fonts remain explicit machine-dependent choices. Box and bubble
frames record padding, border/fill and a picked tail tip. Rendered bounds include the
tail. Panel border/inner margin and exact layout captions reuse the layout renderer;
exact mode keeps line breaks and refuses truncation or unsupported scripts. New layout
preview uses existing tools.preview and compares byte-for-byte with committed output.
Legacy text/layout defaults retain old rendering. Text/panel core checks passed (44
in text-panel-core) and both real layout/caption journeys passed (text-panel-browser).
The new binary-alpha test found antialiased Pillow stroke masks; the new hard-edge path
now uses explicit binary masks. Follow-up text/parity/bounds checks passed in
text-panel-hard-masks, with framed caption preview/save/replay passing again in
portable-caption-hard-masks. TypeScript and git diff --check passed; fetched origin/main
remains a090351. Full acceptance/independent review and maintenance audit remain pending.

Further implementation and verification:
- Material tray search/library reuse, subject/background/prop roles, layout thumbnail
  chooser/drag targets, and saved-take thumbnails implemented. A real-core material
  journey exposed missing composition defaults; width and position now start valid.
- Final-result preview uses isolated session/store metadata and normal replay. Eight
  preview checks passed under final-preview-corrected. Three browser journeys passed
  under material-final-preview (material roles/persistence, downstream preview/cancel,
  cutout repair/reopen). First failed preview test was approval-wait setup and is retained.
- Cutout zoom added. Output.loop moved after caption to preserve positional callers.
- Export presets validate with the existing export schema and persist in settings.
  Five focused checks passed under export-presets; export-presets-browser passed real
  reload/use/prepare/save with encoded bytes and dimensions checked.
- Exact caption case/spaces/blank lines, boxes, alignment and overflow controls added.
  All 25 affected text tests passed under exact-text, including legacy parity. The
  exact-text-browser run is pending at this entry. Portable fonts, panel framing and
  focal points remain outstanding; other unchecked scope is still outstanding.

Latest follow-up:
- Caption save/reopen/replay and layout focal-point browser journeys passed in
  creation-controls-corrected. That run's export test failed because automatic
  output selection remounted the batch dialog; source selection is now pinned.
- Multi-size export passed in export-multiple-sizes, checking 240x160 and 120x80
  outputs and saved bytes. Batch stop/failure retention still needs a targeted test.
- Imported GIF original selection and real UI/core export passed in
  animated-export-browser, checking two frames, 80/170 ms durations and loop count 3.
- Layout focal-point and hard-alpha pixel checks passed in layout-focal (2 tests).
- The earlier caption browser failures were import readiness and a duplicate
  manual-tools CSS class; library now has its own class. Layout test lookup was
  corrected to use its actual accessible combobox name. Failed logs retained.
- TypeScript and Python Ruff passed. Full maintenance/import/unused checks and
  independent diff review remain. Latest origin/main fetch still a090351.
- Still outstanding: direct recorded-element selection; portable fonts and panel
  framing/bubbles; unified intake/HEIC/decoder setup; manual undo/redo and recent
  projects; named cross-project designs and batch rows; GIF editor; native capture.
  Keep the goal active and continue; this is not a completed collection.

Manual history follow-up:
- Reused BranchSnapshot for bounded, persisted manual undo/redo (30 entries),
  tracking imports, tools, step edits/deletion, effect controls, creative settings,
  saved-material/media/collection imports and recipe batches. Undo restores active
  branch visibility and timeline without removing exported files. Redo clears after
  a new manual mutation; branch switches and AI turns clear manual history.
- History RPCs use the existing document revision/idle/actor guards and provider
  retirement path. Frontend replacement handling resets selections after undo/redo.
- manual-history: 15 history and existing branch checks passed.
- manual-history-persistence: 7 history/old-project checks passed.
- manual-history-corrected: UI undo/reopen/redo/new-edit and existing media import
  workflows passed (2). First browser failure was a stale UI revision after a
  separate test client reopened the document; guard correctly rejected it, and
  the test now reloads the reopened view before interacting.
- manual-history-boundaries: 9 focused history and recipe cancellation checks
  passed, including pending-operation refusal and no swallowed errors.
- Project home/recent files remains unimplemented. Manual history still needs the
  independent final review and all scope remains active.

Project home and named design follow-up:
- Projects home uses the existing settings owner for 20 bounded local previews and
  paths, guarded sessionActions for reopen/recovery, search, missing-file status,
  and remove-from-recents without deleting files. project-home passed 3 core checks;
  project-home-browser passed real save/preview/search/cancel/discard/forget. The
  existing killed-core recovery journey now enters through home and passed under
  project-home-recovery, retaining worker cleanup and restored-byte assertions.
- Recipe version 2 captures distinct image roles and named text defaults. Version 1
  retains its existing single-input behavior. Design library persists validated
  recipes in settings across projects; image defaults cannot retain project refs.
- Per-row batch results expose completed output/error/cancel status; individual
  retry creates new output while retaining earlier bytes. Bounded at 12 rows,
  60 operations, 32 roles and 40 steps per design.
- named-designs passed 7 core checks including legacy compatibility, actual role
  pixels, defaults, retry and cancellation. named-designs-browser passed all three
  real recovery/cancel/cross-project capture/retry journeys. A final core validation
  refinement is pending its focused rerun at this entry.
- Protocol registry expected list now includes the four deliberately added history
  and project endpoints; its existing method-registration check passed.
- Still outstanding: direct recorded-element selection, portable fonts and panel
  frames/bubbles, unified HEIC/media intake and decoder setup, full GIF editing,
  native region capture, independent review and remaining acceptance audit.

Final check for this slice: named-designs-final passed 5 focused tests after the
validation refinement. Ruff and git diff --check passed; fetched origin/main is
still a090351. No remaining feature was removed from the objective.

- [x] Persistent material tray and contextual actions: reuse session artifacts and library queries; selecting material exposes relevant existing operations without importing it twice.
- [x] Select recorded picture elements: derive selection from paste/text/layout steps, preview the final dependent result, apply through session editing, cancel without mutation.
- [x] Binary cutout repair: keep/remove polygons preserve source RGB, hard alpha and reproducible replay; corrections survive save/reopen and can enter Cast.
- [x] Text and panels: exact words and line breaks survive edits, overflow is explicit, frame/focal controls preview before committing.
- [x] Export: custom bounded dimensions, fit/matte controls, understandable size budgets, actual encoded-byte feedback, animation preservation and combined prepare/save. Errors retain the source.
- [x] Unified imports: HEIC, supported pictures, clips and pages enter the existing artifact/media paths; decoder availability is explicit; cancellation retains completed imports.
- [x] Manual undo/redo and project home: transaction boundaries restore dependent results, thumbnails identify projects/takes, external exports are never silently deleted.
- [x] Named reusable designs and batch rows: extend recipes with named inputs, persistent library storage and per-row previews/retry; cancellation retains completed outputs.
- [x] Short GIF editing: bounded frame strip, trim/crop/captions/speed/reverse with preserved timings and animation-aware export.
- [x] Native region capture and annotations: deliberate platform capture feeds ordinary imports; cancellation creates no artifacts; verify on private desktop.

## Verification

Implemented since the named-design follow-up:
- Recorded paste/text/layout element bounds feed canvas selection and the existing
  edit/replay controls. Unknown geometry changes stop selection propagation.
  recorded-element-pixels, recorded-elements-replay and recorded-element-boundaries
  retain the focused pixel, browser/reopen and geometry-boundary evidence.
- animation_edit records frame ordering, timing, trim/crop, caption ranges,
  reverse/ping-pong and holds. The existing preview endpoint returns actual GIF
  bytes without committing. animation-edit-final-core (6),
  animation-frame-thumbnail (1), animation-edit-complete-journey (1) passed.
- Bundled portable captions, box/bubble frames and exact panel text now reuse
  existing renderers. Text preview precedes first apply; layout preview uses the
  existing endpoint. text-panel-core (44) and text-panel-browser (2) passed.
  Binary-alpha boundary tests caught nonbinary Impact/WordArt stroke masks;
  explicit one-bit masks fixed them. text-panel-hard-masks and
  portable-caption-hard-masks retain passing post-fix checks. Failed evidence
  remains available under text-panel-boundaries.
- Latest upstream fetch advanced from a090351 to fb1ad675546bd466d5578fbf324a72361458a619
  (persistence/CLI cleanup). Reviewed all overlapping files: types.ts only removes
  unused exports; project.py removes find_autosave; test_server_app switches old
  find_autosave assertions to autosave_path. Current additions do not call the
  removed helper. No upstream integration was performed; reconcile at integration.

HEIC follow-up (2026-11-13):
- Added pillow-heif to the locked runtime and frozen-core package collection.
  Ordinary imports retain HEIF originals and produce existing working PNGs;
  UI previews use artifacts.frame when the original format is HEIF.
- heic-worker was an invalid run: the transfer refused two locally generated
  Linux files, so the newly selected tests were absent. Compared the generated
  lockfile and wire types byte-for-byte with Windows before reconciling their
  sync hashes; no unrelated Linux changes were overwritten.
- heic-worker-synced passed all 3 selected core checks: worker-only decoding,
  original/working bytes across reopen, malformed-file atomic refusal, and the
  existing worker animation/project/collection path.
- heic-browser passed the real file-input/display/save/reopen journey (1 test).
  TypeScript and git diff --check passed.
- Added HEIC import/frame/original-byte persistence to the existing frozen smoke.
  Linux frozen build/smoke evidence is under heic-frozen: build and both normal
  EOF/forced-termination smoke runs passed. Actual bundled HEIC decoding, PNG
  frame preview and original-byte persistence passed; neither left a worker.
- Remaining: unified intake and cancellation, bundled video/PDF decoders,
  deliberate native capture/annotation, final acceptance/maintenance review.
  No installer or Windows/macOS HEIC validation is claimed.

Bundled PDF follow-up:
- Replaced pdftoppm with locked pypdfium2/PDFium in MediaSources, keeping the
  existing serialized worker, timeout/cancellation owner and immutable cache.
  Page rendering is bounded to 1000 pixels on its longest side with smoothing
  disabled. Native document/page/bitmap handles are explicitly closed.
- Removed the obsolete missing-Poppler UI/error path. Invalid/encrypted documents
  and absent pages receive explicit errors; no source is sent to a provider.
- bundled-pdf-core: 3 focused checks passed, including no external commands,
  malformed/absent-page refusal, frozen source-independent pixels, and persistence.
- bundled-pdf-browser initially read a crop before completion. The corrected
  journey waits for done plus a real output; bundled-pdf-browser-complete passed
  actual second-page pixels, selected region dimensions and reopened byte equality.
  TypeScript and Ruff passed. pdf-frozen build and both smoke modes passed:
  bundled PDF rendering/crop/source deletion/persistence, HEIC import/preview,
  guarded save/open, normal EOF and forced death without orphaned workers.
  Each frozen decoder run now has retained logs and summary.json.
- Safeguard changes: the old optional PDF skip is removed because the runtime now
  includes the decoder. The missing-decoder assertion is replaced with malformed
  PDF refusal, while the real render test disables executable lookup and checks
  decoded pixels and persistence. Existing video/tool timeout controls remain.
- Maintenance before the PDF slice: all 3 import contracts, Ruff, high-confidence
  Vulture and strict Knip passed. The growth report is retained under
  workflow-maintenance; dependency and rewritten-assertion signals still require
  the final all-feature review. First import/Vulture attempts lacked quality tools;
  their failure logs remain beside the passing runs after locked-tool installation.

Start with affected Python tests and one real browser/core journey per behavior.
Check encoded output, persisted/reopened data, cancellation and cleanup. Native changes
need private-display evidence; installer/codec packaging needs platform release checks.
Use the existing task baseline and reusable isolated Arch worktree. Record precise
outcomes under artifacts/verification. No live provider requests are needed.

## Product boundary

User-approved selection repair extends the historical manual-editing restriction.
No generated pixels, feathering or blending; deterministic engine/session operations
remain the source of truth. Work in reviewable behavior-sized changes.
