# BadShop: accessible power and a coherent editing workspace

Date: 2026-11-15

Status: proposed implementation design; no application changes made

Source baseline: `2c08d29280057d28887a80e8c1475a86f777c01e`

Scope: all twelve recommendations from the UX review in the accompanying chat

## 1. Intent and evidence

Make the existing creative engine easier to discover, operate and trust. A newcomer should make a joke with their own picture, change any of its words, and share it without configuring AI or learning replay. A returning creator should manipulate recorded elements, compare takes, reuse characters and recipes, and supervise an assistant without losing their place.

The review inspected source, current workflow guides and repository screenshots. It did not measure task completion with users, benchmark rendering, or exercise the installed app. The screenshots were captured on November 12 and do not show every current control. Statements about friction are hypotheses supported by the interface structure, not measured usability failures.

The user requested a detailed design for all twelve recommendations. The terminology, layout, timings, API additions and sequencing below are design decisions proposed by this document, not separately confirmed user preferences. They are explicit so implementation does not require another round of product interpretation.

### Comparison principles

| Reference | Pattern to adopt | Application here |
| --- | --- | --- |
| [Imgflip meme generator](https://imgflip.com/memegenerator) | Short template → text → output path | Complete caption editing remains in Quick ideas. |
| [Canva template editing](https://www.canva.com/design-school/resources/using-and-customizing-templates/) | Selection exposes relevant controls | Click recorded content to edit its parameters. |
| [Photopea layers](https://www.photopea.com/learn/layers) and [text](https://www.photopea.com/learn/text) | Clear editable structure | Name the selected object and distinguish it from execution History. |
| [GIMP nondestructive filters](https://www.gimp.org/release-notes/gimp-3.0.html) | Revisit effects without flattening the editing model | Surface existing effect adjustment and bypass. |
| [ComfyUI workspace](https://docs.comfy.org/interface/overview) | Simple workflow entry points over detailed execution | Run a recipe from named inputs; retain advanced step authoring. |

These are interaction references, not feature-parity targets or invitations to use generative pixels.

### Existing capabilities to preserve

Quick ideas, recorded-element selection, parameter-based placement, hard-alpha cutout repair, draft and downstream previews, manual undo/redo, effect bypass, AI pins, turn checkpoints, branches, cast, recipes, remix files, export profiles, accessibility preferences and project recovery already exist. Do not implement parallel versions of them.

Authoritative guidance: [documentation index](../../README.md), [architecture](../../architecture.md), [manual controls](../../manual-controls.md), [compatibility](../../compatibility.md), [development](../../development.md), and [state machines](../../state-machines.md). Some prose still mentions older project schemas; the current source baseline uses portable schema 6. Serialized contracts and source take precedence over those older descriptions.

## 2. Boundaries and success criteria

### Non-negotiable boundaries

- No image-generation or inpainting model; retain existing engine pixel algorithms, hard alpha and nearest-neighbor geometry.
- Canvas manipulation changes recorded tool parameters. It does not add a general-purpose raster editor or an independent layer document.
- Python session state remains authoritative. React owns selection, navigation and uncommitted drafts. Tauri owns native dialogs, clipboard and lifecycle.
- Retain stable invocation/output-port bindings, provenance, revision guards, operation receipts, approvals and recovery semantics.
- Preview never adds project artifacts, changes history, contacts remote sources, downloads assets, or writes exports.
- Existing working-resolution limits remain. This project does not add full-resolution rerendering.
- No online feed, collaboration service, new telemetry service, new UI framework, or new runtime dependency is required.
- Preserve existing tools and specialist workflows. Remove replaced navigation and duplicate forms as each replacement ships.

### Product acceptance targets

These are proposed targets, not measured results or industry benchmarks:

1. At least 70% of first-time study participants create and copy/export a joke with their own picture within five minutes, without help.
2. At least 80% can revise the headline and both captions of a two-panel layout without entering History or AI setup.
3. At least 80% can select a recorded picture, adjust it, and identify the committed final image without help.
4. Every automated acceptance journey preserves the intended output and edits across save/reopen; incorrect output selection is a failure even if a success notice appears.
5. Keep preview requests bounded and prove draft cancellation leaves project revision, history, artifacts and output folder unchanged.

Use the existing [product study](../../product-study.md) process. Report counts, time, assistance and participant/build context; do not add telemetry to obtain these measurements.

## 3. Workspace and terminology

### Main layout

```text
Projects | project name • | Quick ideas / Edit | Versions | Save project | Share
----------------------------------------------------------------------------
Task panel / material browser | Canvas + view-state label | Selection / History
                             | Select, Undo, Redo, Zoom  | contextual controls
                             |                         | Apply / Cancel
----------------------------------------------------------------------------
Text | Cutout | Compose | Transform | Effects | More tools     AI assistant
Project materials: searchable, windowed thumbnails
```

- Keep two workspace modes: **Quick ideas** and **Edit**. Replace the visible **Art director** workspace label with **Edit**. AI is a panel within Edit, not the name of manual editing.
- **Quick ideas** shows the current joke controls and canvas. History remains available but closed by default.
- **Edit** shows the canvas and selection inspector. The left panel opens the requested task, materials or AI chat. Opening AI does not replace the document or clear an editor draft.
- Keep one inspector instance for the selected recorded step. History selects that inspector; it does not render a competing editable copy of the same fields.
- **Share** replaces the top-level Export label; **Save project** remains separate. Keep existing native shortcuts and project close guards.
- The bottom toolbar has text labels. Narrow layouts may wrap or use a labeled More menu; do not reduce all actions to unexplained icons.

### Responsive behavior

At widths of 1200 CSS px or greater, allow task panel, canvas and inspector simultaneously. From 900–1199 px, keep canvas plus one side panel, with Inspector/Materials/AI/History tabs. Below 900 px, use Canvas/Controls/Materials/AI tabs and keep the primary Apply or creation action visible in the active panel. These are proposed layout thresholds, to verify at 100% and 200% text scale. Do not permit horizontal page scrolling or sticky actions that cover focused controls.

Preserve existing panel resizing, density, text scale, themes and reduced motion. Theme work in another local worktree touches App, QuickStart, Viewer, Timeline and Chat; reconcile with its final styles before implementation. This design sets behavior and hierarchy, not replacement theme tokens.

### Vocabulary

| UI term | Meaning | Existing internal concept |
| --- | --- | --- |
| Project | Editable file and its active document | Session/project |
| Take | Alternate editable version inside a project | Branch/direction/checkpoint copy |
| Versions | The place to compare/manage takes | Branch management UI |
| History | Ordered recorded operations | Steps |
| Materials | Pictures available for the current task | Project artifact uses and saved library |
| My library | Reusable assets and designs across projects | Library and saved designs |
| Final result | Latest completed image result in the active take | Derived output selection |
| Draft preview | Disposable render of uncommitted parameters | Preview response |

Keep user-authored names verbatim. Replace UI labels such as Branches, Saved takes and Images & directions consistently; preserve internal RPC names and serialized fields. Do not rewrite conversation text or migrate saved branch names just for terminology.

## 4. Shared interaction contracts

### Selection, output and drafts

Selection and canvas output are separate: editing an earlier element must not automatically replace the canvas with that step's intermediate image. Continue using stable invocation/output-key selection through `outputSelection` and document selectors. Never identify a result by list position when a named port exists.

An editor draft belongs to `(documentGeneration, active take, invocation identity, base document revision)`. New-tool drafts also include tool name and selected input artifact uses. One draft is authoritative for a given editor; Quick ideas and the inspector must not independently edit the same step. Switching those presentations transfers the draft. Closing the editor, selecting another editable target, changing takes or opening a project with a dirty draft offers **Apply changes / Discard changes / Keep editing**. Viewing a material without replacing the target does not discard the draft. Clean navigation never asks.

Uncommitted drafts are not persisted or autosaved. After a crash, show the last committed project; do not imply that draft work was recovered. If an external mutation changes the base revision, preserve the visible draft, mark it out of date, disable Apply and preview, and offer **Reload saved controls** or **Copy draft values**. Do not automatically merge stale parameters.

### Imports made from an open draft

An import launched by the current editor is a separately committed material action, not a parameter edit. Record its operation UUID, document generation, take, base revision and the edited target/suffix fingerprint before starting. Its response must identify the accepted base revision, resulting revision and imported artifact use; add these typed fields to the relevant local/library/material import responses where absent.

Advance the draft base revision only when the response belongs to that exact operation, the current document/take is unchanged, the current revision equals its resulting revision, and the edited step parameters, bindings and replay suffix still match the captured fingerprint. Preserve all typed draft fields and assign only the chosen image field. A stale/mismatched receipt or any intervening unrelated mutation triggers the ordinary out-of-date state; do not infer safety from similar pixels or a matching display step number. The same rule applies when the active editor is authoring a new tool, using its captured input selection instead of an existing target step.

Canceling the editor discards parameter changes but retains the separately imported material and its normal Undo entry. Say **Picture added to Materials; changes to this joke were canceled.** Canceling the picker before import creates nothing. Canceling an acquisition after admission uses its operation outcome: a completed import stays in Materials, a failed pre-publication import adds nothing, and an uncertain response is reconciled through operation inspection before retry. A canceled editor must never reopen itself or assign a late result automatically.

### Applying an edit and replay

The baseline uses `steps.edit` and `steps.replay_from` separately. Replace the normal UI Apply sequence with an explicit combined mode on the existing `steps.edit` owner, rather than another mutation service:

- Add optional `replay: "none" | "local"` to `steps.edit`; existing callers omitting it retain existing `auto_replay` semantics. Reject a call supplying both options. The new UI sends `replay: "local"` with the existing revision/operation envelope.
- Preflight the replay suffix using the same registry metadata as preview/replay. Refuse the combined local edit before mutation if any runnable suffix step requires network or file writes. Do not skip such steps silently.
- For a supported chain, retain one command owner and one manual-history transaction across edit and replay. Return existing `stale` information plus a typed replay outcome, completed invocation identities and failed-step information. Regenerate wire contracts from Python.
- An accepted command is not automatically a successful render. Show Apply complete only after terminal replay success. On an engine failure, retain the recorded error/stale state and last available image with an explicit warning. Offer **Undo edit** and **Inspect failed step**; do not claim atomic rollback of engine execution.
- A blocked chain offers **Open History** and **Save changes without replay**. The latter explicitly records stale state and uses `replay: "none"`. Existing advanced replay remains available with a disclosure of network/file side effects and an explicit user action.
- One Undo must restore pre-edit parameters and dependent outputs for the combined local edit. Use existing manual history and receipt machinery; do not invent UI snapshots as undo state.

This addition is justified by the current QuickStart and Timeline callers, which both need a reliable Apply action and one undo boundary. Test intermediate failure and uncertain RPC completion as well as success.

### Canvas view-state labels

| State | Required label and action | Sharing behavior |
| --- | --- | --- |
| Active take's latest completed image | `Final result · Take name` | Share that exact output port/artifact use. |
| Explicit earlier result or imported material | `Step N output` or `Source picture` + `Return to final result` | Share the explicitly labeled selection; never silently substitute latest. |
| Before mode | `Before step N` | Share only after the dialog identifies this exact before image. |
| Draft single-step render | `Draft preview · This step only` | Disable image sharing from the draft; offer Apply or Return to saved image. |
| Draft downstream render | `Draft preview · Includes later steps` | Same rule; previews never become exportable artifacts implicitly. |
| Stale/error output | `Last successful image · Changes not fully applied` | Require choosing that saved image explicitly before sharing. |
| Named output disappeared | `This output is no longer available` | Disable sharing; offer Return to final result. |

Final result is a derived default, not a new persisted project field. Choose the latest completed, non-rejected image-producing step's primary registered output; if it has multiple image outputs, show the current named output and an output chooser. If no step output exists, use the most recent working import. If a schema lacks primary-port metadata, preserve its existing first-output default and label the chosen result; never silently replace a missing explicitly selected port. A contact sheet or secondary output remains selectable and shareable but is labeled as such. Failed/stale later steps prevent a clean Final result label.

## 5. Detailed changes

### UX-01 — Complete Quick ideas editing

**Current:** `QuickStart.tsx` creates a layout from title, images and captions, then exposes only `captions[0]` for revision.

**Build:**

1. After creation, show **Edit this joke** with Headline and every caption field supported by the recorded layout. Label by slot where available; otherwise Caption 1, Caption 2, etc. Preserve intentional empty strings, whitespace, line breaks and existing case behavior.
2. Populate controls from the selected layout step, not stale starter defaults. Render textareas for multiline text. Reuse registry/schema limits and layout definitions.
3. Show thumbnail-based image replacement for each layout slot. For multi-slot layouts offer **Use this picture in all slots** as an explicit action; replacing one slot must leave other slots unchanged.
4. Apply the full existing parameter object with only edited fields changed. Preserve template, unused parameters, source bindings and seeds. Use the combined local Apply contract.
5. If the selected output has no editable layout ancestor supported by the recorded chain, show **Edit in workspace**; never select an unrelated old layout to populate a misleading form.
6. Keep **Duplicate take** next to Apply and **Share** next to the result. Duplication with a dirty draft uses the shared dirty-draft decision first.

**Acceptance:** Create a two-slot layout, edit title and both captions (including an empty caption), replace only the second picture, Apply, Undo/Redo, save/reopen and verify parameters, slots and output pixels. Invalid text/layout input leaves the draft available and the committed output unchanged. No provider/network calls.

**Owners:** `QuickStart.tsx`, existing layout definitions, `ToolForm.tsx`, `steps.edit` and replay. Do not change text-rendering algorithms or invent a parallel layout model.

### UX-02 — Default canvas selection and contextual editing

**Current:** `Viewer.tsx` initializes recorded-element selection off. `recordedElements.ts` walks supported paste/text chains and layout slots; unknown transforms stop traversal.

**Build:**

1. Enable **Select** by default for committed images with recorded bounds. Hover/focus outlines are UI overlays only. One click selects the topmost supported element; show its name and appropriate controls in the inspector.
2. Provide an always-accessible **Elements in this image** list for overlap and keyboard selection. Use stable identity: invocation ID plus slot key/index where needed. Two layout slots must not be indistinguishable merely because they share a step.
3. Paste elements expose Replace picture, Move, Width, Rotation and Flip through existing correction controls. Text elements expose Words, Size, Alignment and existing frame options. Layout slots expose their associated picture/caption controls; selection does not promise freeform repositioning of fixed templates.
4. Double-clicking a supported caption focuses its text field. It does not launch OCR or infer text from flattened pixels. For layout headlines without recorded bounds, expose Headline in the inspector after selecting any slot; do not invent a canvas hit region.
5. Drag placement and keyboard nudges update draft parameters, with pointer capture and Escape cancellation. Preserve existing 1 px / Shift 10 px movement. Existing restrictions on rotation/resize handles remain visible.
6. Coordinate picking and cutout repair temporarily own canvas input. Suspend object selection until they finish or cancel. Clicking blank canvas clears the object selection without changing the displayed artifact.
7. When recorded bounds are unavailable, show **This image has no selectable recorded elements. Open History to edit its steps.** Unknown transforms must not produce inaccurate hit areas.

**Acceptance:** Select overlapping objects with mouse and keyboard, edit an early paste while retaining the final canvas, preview and apply, then save/reopen. Verify bounds and output pixels. Test unknown transforms and duplicate slot labels; no fabricated selection.

**Owners:** `Viewer.tsx`, `recordedElements.ts`, `CorrectionControls.tsx`, `store.ts`, existing step metadata. No general layer model or new persisted object IDs are needed for supported bounds.

### UX-03 — A visible manual editing workspace

**Build:** Rename Art director to Edit and expose the labeled toolbar from §3. **Effects** opens existing effect categories; **More tools** opens the complete searchable catalogue. Text, Cutout, Compose and Transform directly open the same forms used by the catalogue.

**Compose** begins with two visible thumbnail fields, Subject and Background. Prefill from recorded material roles. Without distinct valid roles, require the user to choose missing inputs rather than silently pasting an image onto itself. The same image is allowed only after explicit selection. Use the existing paste defaults after selection and preview before applying.

AI opens a left panel with existing chat/provider controls and a clear setup link if no provider exists. Manual controls remain usable with no provider. Provider setup never appears just because the user opens Edit.

Keep stored workspace values `quick` and `advanced` for this release; `advanced` now renders Edit. Do not reset existing preferences. Remove the old duplicate Manual tools accordion once its actions have moved into the toolbar.

**Acceptance:** With no providers configured, import subject/background, compose, caption and export entirely through Edit. Verify roles, history and pixels. Keyboard users can reach every toolbar action and return focus after closing forms.

**Owners:** `App.tsx`, `ManualTools.tsx`, `Viewer.tsx`, `Chat.tsx`, `ToolForm.tsx`, existing creative source roles.

### UX-04 — Current work before template browsing

**Build:** Model Quick ideas presentation as three states: **Choose format**, **Customize new joke**, **Edit current joke**. After choosing a card, replace the catalogue with the creation form and **Back to formats**. After success, show the revision form first and collapse the catalogue under **Try another format**. The canvas remains visible at desktop widths.

Keep Apply/Make and Cancel in a sticky footer of the task panel with sufficient scroll padding. **Try another format** starts a new layout; it does not mutate an existing template's geometry. Show **Creates another image in this take** and offer Duplicate take beforehand. Back/cancel preserves committed work and uses the dirty-draft rule for unsaved text.

First open with no images shows the sample plus **Use my picture**. An existing project opens the active result rather than resetting to starter defaults. Small-screen creation switches to Canvas after success and offers **Edit words** to return.

**Acceptance:** At 1280×800 and at 200% text scale, create, revise and share without scrolling through the full template catalogue; focused fields and footer actions remain unobscured.

**Owners:** `QuickStart.tsx`, workspace CSS and existing compact-pane logic. No project format changes.

### UX-05 — Explicit preview scope and replay impact

**Build:** Implement the view-state labels in §4. Default an existing-step draft to final-result preview when the suffix is eligible; otherwise label and offer a single-step preview. New tools preview only their proposed output.

Before Apply, show **Changes this step; checks N later steps and reuses unchanged results**. The count follows the actual replay suffix, not a fabricated count of known changed dependencies. If network/file-writing steps block local Apply, identify the first blocker and use §4's advanced path. Disabled previews explain why: missing local asset, busy operation, bypassed effect, unsupported chain, or operation limit.

Before/After compares matching scopes: committed final vs draft final, or committed step vs draft step. Never compare a draft early step against an unlabeled final image. When the last saved image is still displayed during rendering, mark **Updating preview…**; only the matching latest response can remove that label.

**Acceptance:** Edit step 2 of a chain with later effects; preview reflects those effects and Cancel leaves state unchanged. A chain containing export produces no file from preview or local Apply. A failed replay cannot produce a success notice or a clean Final result label.

**Owners:** `ToolForm.tsx`, `Timeline.tsx`, viewer selectors, session preview/edit/replay and registry metadata. Share replay eligibility calculation in the core; the UI consumes the result rather than maintaining an independent tool safety list.

### UX-06 — One Versions surface

**Build:** Place Versions in the header. It opens a panel of take thumbnails with active badge, name, manual/automatic origin, and explicit **Open take**, **Duplicate**, **Rename**, **Keep**, **Delete** actions where supported. Viewing a comparison must not switch the active branch.

Select up to two takes for side-by-side, fit-to-pane comparison. Use each stored preview artifact and label its dimensions; do not run tools to make comparisons. **Open take** performs the existing guarded branch switch. On success show **Editing: name**; on failure keep the current take and its canvas. Keep/rename promotes an automatic take using existing retention rules. Do not add a new retention policy.

Show **Takes are stored inside this project. Save project to keep them on disk.** after duplication in an unsaved project. Preserve explicit takes, current automatic retention and AI undo checkpoints. Distinguish **Undo edit** from **Undo AI turn**; do not imply a common unlimited history across take switches.

Remove the separate branches tab and Saved takes UI after both route to this surface. Preserve challenge round identity and sanitized display labels.

**Acceptance:** Duplicate, change, compare without activation, switch, rename, save/reopen and restore exact selected output. Deleting a take never removes a shared blob still referenced by another take. Dirty drafts and running operations block/safely guard switching.

**Owners:** `Studio.tsx`, `QuickStart.tsx`, `directions.ts`, branch RPCs and `session/branches.py`.

### UX-07 — Contextual material destinations

**Build:** Replace the ten-destination Images & directions modal with a docked browser whose top-level destinations are **Find material**, **My library**, and **Formats**; Versions is separate. A compact-screen browser may be a modal, with the same routes and focus handling.

| Existing destination | New home |
| --- | --- |
| Find images; Clips, pages & folders | Find material → Online / Local files and clips |
| Junk drawer; Recent choices; cast | My library → Pictures / Characters / Recent |
| Layouts & packs; Retro workbench | Formats → Layouts / Retro / Packs |
| Idea mixer; Image pairs | Formats → Explore ideas / Pair pictures |
| Sprite sheets | More tools → Sprite sheets |
| Branches | Versions |
| Project recipes and saved designs | My library → Recipes, with Project / Saved library scopes |

Callers open the relevant destination with a purpose such as Replace slot 2, Choose subject, Choose background or Attach to AI. Candidate actions say **Use as background** or **Replace this picture**, not an ambiguous Use image. Importing from search must not always attach to chat; attach only for an explicit AI-attachment caller. Import and library mutation remain explicit actions.

For contextual replacement, do not call the current `Studio.acquire()` flow, which appends an `acquire` producer after the target step. Earlier steps cannot depend on later producers. Add user-only `materials.discover` and `materials.acquire` handlers at the existing core material/server boundary. Both use the existing registered discovery/acquisition implementation, session-owned bounded executor and disposable scratch storage; they do not introduce another downloader, image decoder or pixel engine.

`materials.discover` accepts the existing validated discovery parameters and returns bounded candidate metadata/previews without publishing a History step or contact-sheet artifact. It is an explicit online search, never a background preview request. `materials.acquire` accepts the existing validated candidate URL/source parameters plus expected revision and normal mutation operation UUID. It acquires in disposable storage, then checks document/take ownership and revision again before publishing the downloaded bytes through the same `Session.import_image` path used by local files. Publish one independent imported artifact use with original/source credits intact and one manual import undo entry. Preserve metadata supplied by the source without claiming to verify its licence. Keep the current URL/network/size/decoder guards and worker limits. Clean scratch files on success, error, cancellation and stale ownership; no late result may enter a replacement document.

This import has no timeline producer and is a valid input to an earlier edit under the existing dependency rule. Do not relabel a later produced artifact as an import, strip its producer, reorder History, or exempt it from `_refuse_later`. Existing manual/AI `discover` and `acquire` tools remain available as recorded operations. For a replacement picker, disable later-produced candidates with **Made after this step; choose an imported or earlier picture**. Do not silently snapshot a descendant into an input. The new materials routes are specifically for acquisition of independent external material, not arbitrary conversion of later outputs.

After a material import, use the guarded draft-revision transition in §4. Cancel retains that committed material; failed assignment does not delete a successful import. Local and saved-library selections continue through their current import handlers with the same receipt/revision contract.

Retain source/rights information, availability explanations, thumbnails, windowing and 50-entry library pagination. Preserve query/filter/scroll state for the lifetime of the browser within the current project; clear target identity on project replacement. Cancel leaves the draft and target unchanged. A target invalidated while browsing refuses assignment and offers reopening the current selection.

**Acceptance:** Search/import or choose a saved material directly from a slot picker, return to the same draft, and replace only that slot. Exercise failed import, canceled selection and project replacement during import. Existing specialty destinations remain reachable. Specifically test create layout → type unsaved caption → search/acquire replacement → apply: there is no later network producer, the typed caption survives import, and save/reopen preserves the replacement source credits. Race an unrelated edit against import and require safe refusal without overwriting it.

**Owners:** `Studio.tsx` and its existing children, `LibraryImage.tsx`, `libraryPage.tsx`, image pickers and role setters. Split presentation components only where these actual callers need reuse; no new asset store.

### UX-08 — Small primary forms and task-oriented search

**Build:** Add presentation-only per-tool metadata for basic fields, grouping and search aliases. Keep it in one frontend module consumed by the inspector and tool catalogue. The Python schema remains the validation/default authority. Every field not listed as basic remains reachable under **Advanced controls**; no parameter is dropped on submit.

Initial groups:

| Tool family | Basic controls | Advanced examples |
| --- | --- | --- |
| Text | Words, font, size, color, align, fitting | Detailed frame/tail parameters, naming |
| Paste | Subject/background, placement, width, rotation, flip | Scatter/repeat, naming |
| Cutout | Method, target/region, repair | Method-specific specialist options |
| Transform | Crop, dimensions, rotation, flip | Remaining schema options |
| Deepfry | Strength and tint | Seed, naming |
| Other effects | Input plus meaningful effect controls | Seed, naming and uncommon controls |

Do not hide a required field without a usable default. A validation error in Advanced expands and focuses its field. Changing Basic controls preserves Advanced values. Seed remains recorded; randomized defaults must not change on rerender or preview.

Search indexes name, summary, category and aliases. Seed aliases include remove background → cutout; put picture on picture → paste; add words → text; pixelate/blur face → censor where supported; resize/rotate → transform. Rank exact name, prefix and then token matches; show actual tool names and summaries. No network or model search. Unsupported queries show suggestions without claiming an unavailable tool.

**Acceptance:** Find tools from aliases, set an advanced seed, edit basic strength, apply and reopen with seed intact. Advanced validation errors are visible and focusable. Tool-catalog coverage and generated schemas remain intact.

**Owners:** `ToolForm.tsx`, tool palette in `Timeline.tsx`, small shared presentation metadata; no duplicated validation schema.

### UX-09 — Bounded automatic previews

**Build:** Reuse `tools.preview` for new tools and `steps.preview` for existing edits. Add typed core preview planning metadata (see §6) for eligibility, scope, replay count and refusal reason. Automatic preview is on for eligible local edits, with a visible toggle that persists as a UI preference.

- Debounce text/number changes by 300 ms. Render after pointer release for placement drags; during dragging show geometric guides only. Keyboard nudges debounce by 150 ms.
- Admit at most one automatic preview per active editor with one replaceable pending request. A new draft replaces the pending request, not an unbounded queue.
- Key results by document generation, take, revision, target, scope and canonical parameter fingerprint. Ignore obsolete results. Do not pretend ignoring a response cancels its worker.
- Initially let an in-flight preview finish under existing worker deadlines. Closing/canceling the editor drops pending work, ignores its result, and releases UI URLs; the core cleans disposable stores in `finally`. Do not add worker termination solely for interactive cancellation.
- Apply waits for in-flight preview completion, then submits the current draft with a fresh revision check; preview success is never a prerequisite for Apply if preview is unavailable for a non-safety reason. Preview errors remain separate from validation errors.
- If a preview takes over one second, show **Rendering preview…**. After a completed preview taking over two seconds, pause automatic refresh for this editor and show **This preview is slow. Update preview** plus **Resume automatic preview**. These are initial UX thresholds, to tune from measured traces.
- Keep at most one current preview and one comparison image in the editor. Release obsolete decoded images/object URLs promptly. Retain existing media byte limits and avoid adding unbounded base64 caches.

No background asset download is allowed. Missing model/font assets produce a setup action outside the preview operation. Final-result previews retain the 60-operation cap and local-only restrictions.

**Acceptance:** Rapid edits finish with only the latest valid preview visible, bounded requests, no project mutation and cleaned scratch resources. Project/take switches and disconnects cannot paint an old preview. Measure warm/cold render time separately on real local fixtures; do not assert that all tools meet an invented latency budget.

**Owners:** shared editor preview lifecycle used by `ToolForm.tsx` and Quick ideas, existing preview handlers, `session/session.py`, worker limits and media lifecycle.

### UX-10 — Visual AI approvals and intent-based protection

**Build:** An approval card names the action, target image, changed fields and reason, and shows input thumbnails. Show **Approve**, **Edit proposal**, **Reject**, with the existing rejection note. Keep raw parameters expandable. Pins use **Keep these words**, **Keep this placement**, **Keep these pictures**, mapped to existing locked fields and their actual protection limits.

The current `steps.preview` requires idle state and cannot preview a waiting approval. Do not remove that guard. Add a user-only `approval.preview` command owned by the existing gate coordination path:

1. Verify document/take/revision and stable pending proposal identity; confirm the proposal is still waiting in the API or CLI gate.
2. Validate the proposed or edited parameters with the same rules as an edited approval. Reject network/file-writing tools and missing local dependencies before execution.
3. Capture immutable inputs and run the existing local preview executor in a disposable snapshot. The real proposal remains pending. This is a narrow preview admission exception, not general permission to edit a busy session.
4. Limit to one approval preview per document, sharing the editor's preview admission budget. Display it only if the gate/proposal/revision still matches at completion.
5. Stop, Reject or another client's resolution remains available while rendering; it revokes preview display and cleans resources. Never hold the gate lock across expensive rendering. Never auto-approve after preview.

Approval preview is explicit, not automatically run on every incoming proposal. Label **Proposed result for this operation**; future AI operations are unknown. Non-previewable proposals still show an honest textual summary and reason. Invalid edited parameters leave the approval waiting and editable. API and CLI approvals have the same user-facing behavior.

After a completed AI turn, show existing **Undo AI turn** and **Duplicate take**. Starting an AI turn while a manual draft is dirty first resolves that draft; do not silently clear it. Keep usage/cost unknown when providers do not report it.

**Acceptance:** With a scripted provider, preview a waiting local proposal without changing project artifacts or resolving approval; reject it, then approve a valid edited proposal and inspect pixels. Repeat the gate flow through the CLI bridge fixture. Stop while previewing, stale responses, invalid edits and blocked network/export proposals must retain existing authority boundaries.

**Owners:** `Chat.tsx`, existing approval form, `server/app.py`, approval gates, session preview executor and pins. Run the approval-dependency negative control when changing its covered guard.

### UX-11 — Reuse at the moment of success

**Build:** Add contextual actions with persistent homes, not automatic saving:

- After a successful cutout or on a selected material: **Save character** opens existing Cast controls prefilled with that image. Require a name; expression/collection remain optional. Show **Saved in My library** after success.
- On a completed image-producing step: **Reuse these edits** opens recipe capture. Start with the selected step using existing capture semantics. Offer **Add another recorded step** through the existing append path; do not imply that a whole dependency chain was captured automatically.
- Recipe opening defaults to **Use recipe**: named image/text inputs for one run, defaults preserved, result thumbnail and Run. Put step references, capture/append and raw parameter forms under **Edit recipe**. Batch rows are an explicit **Run on several pictures** expansion.
- Use existing recipe version-2 input definitions and saved-design storage. Version-1 recipes retain their existing input-picture picker. Do not invent named inputs for a legacy recipe without explicit authoring.
- Make storage scope explicit: **Save in this project** versus **Save to My library**. Project save does not replace a library save; library deletion does not erase referenced project assets.
- Beside Share image, expose **Editable remix** using the existing selective exporter and included-image review. Do not substitute full project export or automatically send/upload files.

Keep current limits: up to 12 input rows/pictures and 60 executed batch steps, plus existing recipe authoring limits. Stop preserves completed rows; Retry uses current row values and existing operation receipts. Warn before replacing a same-name library design and retain the previous entry if saving fails.

**Acceptance:** Save a cutout character and named-input recipe, use both in a fresh project, then save/reopen actual outputs. Stop a batch and retry its failed row without duplicating completed rows. Export an editable remix, open it in an isolated profile, edit words and verify excluded chat/other takes remain absent.

**Owners:** `Cast.tsx`, `RecipeStudio.tsx`, `RemixShare.tsx`, recipe capture/run and library/settings owners. Existing named inputs already support the simple form; no new recipe schema is required.

### UX-12 — Predictable sharing and destination controls

**Build:** Share opens a dialog bound to a stable snapshot of the explicitly selected committed artifact use. Show its thumbnail, take/output label, dimensions, format and bytes. Selection changes elsewhere must not silently retarget an open share dialog. A document/take replacement closes it; preparing an export result explicitly updates the target and label.

Primary actions: **Copy image**, **Save image**, **Editable remix**. Animated media uses **Copy still frame** and clearly names the frame; Save original preserves animation. Keep credits alongside the selected output with the existing sidecar option and failure reporting.

Show **Save to: folder** before Save image. **Change folder** uses the existing native folder chooser and updates the normal output-folder preference after selection; explain **Used for future exports too**. Cancel leaves the preference and export target unchanged. Use the current native bridge/settings path, not a second destination store. Display a concise filename/default name preview, with existing collision-safe naming; the final success path is authoritative.

Under **Size and format**, order controls as preset, format/animation, dimensions, fit/background, file-size limit, Prepare/Prepare and save. Put saved-preset creation, deletion and batch output below those controls. Add plain copy: **Edits use a working copy up to 1000 px on the longest side. Enlarging export does not restore original detail.** Do not change existing output dimension constraints.

Export preparations remain ordinary recorded tool outputs. Failed preparation leaves the previous target usable; failed file writing leaves the prepared output available to retry. Never re-run a completed preparation simply to retry its file save. Interrupted external writes use existing uncertain-operation handling; inspect the destination before a retry that could create another file.

**Acceptance:** Share an earlier output while a newer one exists and verify exact exported bytes; prepare dimensions/file budget and verify actual bytes/size; cancel folder selection; fail a write and retry; save GIF and inspect frame count/timing. Project Save still saves editable state separately.

**Owners:** `ShareImage.tsx`, `RemixShare.tsx`, `native.ts`, existing output-folder settings and export handlers. Folder-picker changes require native verification.

## 6. Implementation architecture and contract deltas

### Existing owners and reuse

| Concern | Existing owner | Planned change |
| --- | --- | --- |
| Workspace/navigation | `app/src/App.tsx` | Edit label, panel routes, Versions and Share entry points |
| Quick creation | `components/QuickStart.tsx` | Three presentation states and complete layout draft |
| Canvas selection | `Viewer.tsx`, `recordedElements.ts`, `store.ts` | Default select, slot identity, truthful view-state labels |
| Forms/corrections | `ToolForm.tsx`, `CorrectionControls.tsx`, `Timeline.tsx` | Shared draft/preview lifecycle, basic/advanced presentation |
| Materials | `Studio.tsx`, existing child panels, `libraryPage.tsx` | Contextual routes and target-aware assignment |
| Takes | `directions.ts`, branch RPCs, `session/branches.py` | One Versions presentation; unchanged retention |
| Reuse/share | Cast, RecipeStudio, ShareImage, RemixShare | Contextual entry points and simpler first-use forms |
| Mutations/approvals | `core/src/badshop/server/app.py` | Combined local edit/replay, narrow approval preview admission |
| Preview algorithms | `core/src/badshop/session/session.py` | Shared planning/eligibility and disposable execution |
| Wire contract | `server/contracts.py`, generated frontend wire types | Typed additions generated from Python owners |

### New shared pieces justified by current callers

1. A small editor draft/preview controller shared by Quick ideas and ToolForm. It owns transient draft lifecycle and response correlation, not session state or tool execution.
2. A route/target argument for the existing materials browser, used by slot, subject/background and AI-attachment callers. Avoid a general plugin navigation system.
3. A presentation metadata table for basic fields/search aliases. Registry schema remains authoritative.
4. Typed preview planning returned by a new user-only read command `previews.plan`. Request identifies either `(tool, params)` or `(step_id, params)`, with requested `step`/`final` scope and expected revision. Response includes eligibility, effective scope, replay suffix count, stable blocker invocation when applicable, and human-safe reason code/message. It does not create preview state or execute tools. Both planning and execution call the same core eligibility helper; execution always revalidates.
5. `approval.preview` as specified above. Requests contain pending step identity, proposed parameters and expected revision; responses identify the proposal/revision and scoped preview images. Use bounded response payloads consistent with existing preview handling. No persisted preview IDs or new public media server.

6. `materials.discover` / `materials.acquire` as specified in UX-07, backed by existing registry execution and import publication. Their current callers are image-slot replacement and subject/background selection. Acquisition uses normal operation receipts; discovery is a bounded, read-only operation relative to the project despite doing explicit network I/O. The UI does not send search/acquisition through `tools.run` for these contexts.
7. Add base/result revision and operation correlation to local/library/material import results where needed for the narrowly allowed draft transition in §4. Do not add a second operation journal or persist draft state.

Preview planning reasons: `busy`, `network_step`, `file_write`, `operation_limit`, `bypassed`, `missing_asset`, `invalid_params`, `missing_target`. Admission can determine metadata/availability without importing heavyweight models. An unavailable asset must still be refused by execution even if planning raced with its removal.

For ordinary previews, retain existing base64 response compatibility and add response correlation in the shared controller; changing preview transport is outside this feature unless measured payload limits block acceptance. Register new methods with the same authority, timeout, document ownership and response validation systems as existing handlers.

### Persistence and compatibility

No new portable project schema is expected. All edits use existing params, source roles, locked fields, branches, recipes and artifact uses. UI panel state, automatic preview preference and basic/advanced disclosure are local presentation preferences. Saved takes and recipes use existing authoritative persistence. Opening schemas 1–5 follows existing migration; do not backfill invented bounds or provenance. Older steps without bounds remain editable through History and acquire supported metadata only through explicit replay.

Preserve old RPC callers by keeping omitted edit options at current semantics. The combined mode is opt-in; it is not a temporary fallback to remove. Avoid renaming serialized branch fields. Remove replaced UI implementations in each PR, but retain the advanced catalogue and side-effectful replay as explicit expert functions.

## 7. Cross-cutting interaction requirements

- Every icon-only control has a visible tooltip and accessible name; major task entry points retain text labels.
- Selected, busy, failed and draft states use text/shape as well as color. All shipped themes must remain readable; use current tokens.
- All actions have keyboard equivalents through normal focus navigation. Do not override typing keys in text fields. Arrow-key canvas nudges apply only to a focused placement control.
- Dialogs trap focus and return it to the opener. Docked panels do not trap focus. Escape cancels the active pick/drag first, then closes clean panels; it must not silently discard dirty edits.
- Status announcements are polite for preview progress and success. Validation errors identify their fields; do not announce every keystroke or preview frame.
- At 200% text, controls remain operable and notices do not cover primary actions. Reduced motion pauses animations according to current preferences and avoids animated panel transitions.
- Disconnected or busy mutations show a reason. Reading saved images remains possible where current contracts allow it. Never present a connected socket as evidence that a change committed.
- Autosave/recovery, explicit project Save, export, library Save and draft Apply remain distinct and consistently named.

## 8. Delivery order and removal checklist

Each row is a separate observable behavior change/PR, with only necessary supporting internals. Do not combine all twelve into one implementation PR.

| Order | Deliverable | Dependency | Remove/replace |
| --- | --- | --- | --- |
| A | UX-01 complete Quick idea revision; combined local Apply and its focused regression | None | Punchline-only revision path; UI split edit/replay for this caller |
| B | UX-04 current-joke-first presentation | A | Always-expanded starter grid during editing |
| C | UX-05 truthful output/scope labels and shared preview planning | A | Ambiguous preview/output labels; duplicated eligibility checks |
| D | UX-02 default recorded-element selection | C | Opt-in-only selection discovery; duplicate selection controls |
| E | UX-03 Edit workspace and toolbar | D | Art director workspace label; duplicate Manual tools accordion |
| F | UX-06 Versions | C | Branches tab and separate Saved takes list |
| G | UX-07 contextual materials | E, F | Images & directions modal/navigation; unconditional chat attachment |
| H | UX-08 basic forms and aliases | E | Duplicate parameter presentation lists where superseded |
| I | UX-09 automatic preview | C, H | Independent preview timers/state in affected editors |
| J | UX-10 visual approval and pins | I | Raw-only approval presentation; preserve advanced details |
| K | UX-11 contextual reuse | G, H | Capture-first default recipe experience; retain advanced authoring |
| L | UX-12 sharing/destination | C | Ambiguous Export entry; preset-management-first expanded layout |

The first implementation release should include A–E. Later groups can ship incrementally after their acceptance checks; do not add permanent feature flags solely to keep old and new paths alive. Adapt a phase to intervening upstream changes before implementation.

Each PR must name current callers of new shared code, document maintenance cost, describe safeguard changes, and update the relevant current guide. This proposal remains a dated design; move shipped behavioral contracts into the current documentation owners as work lands.

## 9. Verification plan

This documentation task requires no application test run. For implementation, begin with the smallest affected case and one real UI/core journey. Keep fixtures isolated from personal projects/settings and retain evidence under `artifacts/verification/`. Use the repository's focused runner; broader suites require a stated dependency change, failure, coverage gap or release need.

| Area | Starting existing test/workflow | Required new evidence |
| --- | --- | --- |
| UX-01/04 | `app/e2e/quick-share.spec.ts`, `personal-ideas.spec.ts` | All captions/slots, dirty draft, save/reopen and copy/export pixels |
| UX-02/03 | `material-workspace.spec.ts`, `manual-controls.spec.ts` | Default selection, overlapping slots, no-provider composition, keyboard input |
| UX-05 | `editing-context.spec.ts`, final-preview case in `material-workspace.spec.ts` | Scope labels, failed replay, blocked export suffix, exact exported target |
| UX-06 | `studio.spec.ts`, `playful-workflows.spec.ts` | Compare without activation, retention, guarded switching and reopen |
| UX-07 | `materials.spec.ts`, `material-workspace.spec.ts` | Purpose-aware assignment, target invalidation and no unwanted chat attachment |
| UX-08 | Relevant form/component cases and a manual-tool journey | Advanced values retained, alias discovery and validation focus |
| UX-09 | Preview core tests plus `manual-controls.spec.ts` | Bounded scheduling, delayed obsolete replies, cleanup and no mutation |
| UX-10 | `controller.spec.ts`, `state-machines.spec.ts`, API/CLI gate tests | Pending preview preserves authority; reject/stop wins; approved pixels |
| UX-11 | `cast-recipes.spec.ts`, `cast-sharing.spec.ts`, `recipe-recovery.spec.ts`, `remix-recovery.spec.ts` | Fresh-project reuse, failure retry, selective remix contents |
| UX-12 | `export-preparation.spec.ts`, `editing-context.spec.ts` | Actual output path/bytes, frame timing, failed-write retry and native folder cancellation |

Do not run all files in a row by default. Select the named behavior in those files, adding cases where a gap exists. Core boundary tests are appropriate for operation ownership, replay transaction failure, approval races and preview cleanup; avoid dozens of mocked component assertions duplicating a successful journey.

For changed keyboard, drag/drop, clipboard or folder-picker behavior, exercise the affected native interaction. On Linux use the private Xvfb/D-Bus workflow. Browser dialog fallbacks are not evidence of native dialogs; source builds are not verified installers. Native platform/release checks remain separate gates.

For consequential changes, use [diff review](../../diff-review.md). Run the relevant opt-in negative control when its guarded behavior changes, particularly document ownership and approval dependency. No pixel golden, guard or existing assertion may be weakened to accommodate a new presentation.

### Observed usability session

After A–E, observe five initial participants without coaching as a formative check, then use the larger existing study protocol for the targets in §2. Give these tasks in order: create from own image; change every text field; move a recorded picture; keep two takes and return; share the intended output; save/reopen. Record task time, help, wrong selections and accidental changes. Do not claim five observations establish retention or general market fit.

After F–L, add reuse in a fresh project, a canceled preview, an AI approval rejection, and a failed export recovery. Test with at least one keyboard-only session and 200% text scale. Capture issues against the exact source/release revision and distinguish expected restrictions from defects.

## 10. Design decisions and deferred work

Chosen: two modes (Quick ideas/Edit), optional AI panel, Takes inside Versions, contextual material browsing, explicit commit with disposable preview, and one core edit/replay owner. These choices minimize navigation concepts and preserve the deterministic architecture.

Deferred: general layers, arbitrary transform-aware hit testing, full-resolution rendering, arbitrary image text recognition, online collaboration, new image formats, universal recipe programming, and guaranteed low-latency rendering for every tool. None is needed to satisfy this design.

Implementation may choose component boundaries, exact spacing, animation-free transition details and measured debounce tuning within these contracts. Changes to persistence, approval authority, automatic external effects, supported editable elements, or the twelve promised outcomes require revising this document rather than silently expanding scope.

The design is ready for task planning when the builder check finds no unresolved product or ownership decisions. It is complete as documentation when all twelve IDs have interactions, failure handling, current owners, acceptance evidence and a delivery position. It is not a claim that any of these proposed changes has shipped.
