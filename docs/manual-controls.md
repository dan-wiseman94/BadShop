# Manual corrections

Use **Select elements** on the canvas to outline recorded pictures, captions and
layout slots. Click an outline or choose **Recorded element** for overlapping
items to open that step's existing controls. Selection preserves the final canvas;
**Preview final result** includes later steps before **Apply & replay** commits.
Bounds are recorded when paste/text steps run and survive project save/reopen.
Older steps acquire bounds when replayed. Overlays stop at unknown geometric
transforms; those steps remain editable from the timeline.

Open **Art director**, select a timeline step, and use its quick corrections or
full parameter form. Every committed correction uses the normal session tool
and replay path. The AI sees the updated timeline and manual-change notes.

- **Placement:** drag the anchor or focus its guide and use arrow keys. Shift
  moves ten pixels. Paste controls include width, rotation, flip and a resize
  handle for unrotated pieces. Fit-box placement converts to an explicit centered
  position when moved. Repeated scatter stays in the full parameter form.
- **Captions:** edit exact wording and line breaks together. **Fit these words
  automatically** shrinks the existing text renderer and refuses clipping. Impact
  keeps its existing uppercase style unless **Preserve case** is enabled. New
  manual captions preserve capitalization, spaces and blank lines by default.
  **Box** limits the caption area; **Align** controls left, center or right
  alignment. **Overflow** can shrink all words or refuse clipping. Existing
  recorded captions retain their original wrapping and capitalization defaults.
- **Replacement:** change the Piece image in a paste step. Position, scale and
  rotation remain recorded independently. Preview before applying.
- **Portable font:** new manual captions default to the bundled Aileron font.
  It supports Latin-1 text without font lookup or downloads and is recorded as
  `font: bundled`. Choose a local font for other scripts; local font files must
  also exist on another machine to replay the same lettering. Existing captions
  retain their recorded font behavior.
- **Caption frames:** choose Box or Bubble, padding, background, border color
  and border width. Bubble tails use a tip picked in image coordinates and attach
  to the bottom edge. Framed text uses hard edges; fitting includes frame padding.
  New text can be previewed before Apply. Cancel changes leaves no project artifacts.
- **Preview changes** renders the selected step without adding project artifacts
  or changing its history. The divider compares its existing output with the draft.
  Background choices make hard-alpha cutouts visible. **Cancel changes** discards
  the draft. Network and file-writing steps cannot preview; enable a bypassed
  effect before previewing its settings.
  **Preview final result, including later steps** replays up to 60 local operations
  in a disposable session. It shows the downstream result without publishing
  artifacts or changing history. Network and file-writing chains are refused.
- **Cutout repair:** mark keep/remove polygons on the original image, zoom for
  detail, undo points or regions, and preview before applying. Removal wins where
  regions overlap. Repairs keep original RGB values and use only hard alpha.
- **Variants:** compare three rotation, caption-size or seed choices. Selecting a
  thumbnail changes only that parameter; Apply commits it. Changing other draft
  values invalidates old thumbnails.
- **Pins:** pin source images, caption wording or placement. The core requires
  approval for later AI operations on the protected result or descendants, even
  in Auto mode. Unrelated images remain available. This is a review boundary over
  recorded operations, not automatic recognition or protection of arbitrary
  pixel regions. Manual edits and explicit approvals remain available.
- **Applied effects:** select an effect to adjust its parameters or disable it.
  Bypass replays dependents from its input. Enabling it restores the effect.
  Projects and exported recipes preserve the bypass decision.
  Animated inputs cannot be bypassed; they are refused without changing the step.
- **Pause after operation** finishes the current operation before yielding control.
  An approval wait can pause immediately. **Pause before finishing effects** yields
  before finishing/export tools. **Resume and allow finishing** acknowledges that
  checkpoint and starts a continuation using the corrected state.
- **Undo last AI turn** restores its checkpoint and preserves the attempt as a
  direction. Visiting a checkpoint creates an editable copy. Undo is unavailable
  for turns started while an independent caller owns a pending operation.
- The viewer's **Undo** and **Redo** restore manual imports, tool runs, edits with
  their dependent replay, effect controls, creative settings and recipe batches.
  Up to 30 entries persist in the project. A new manual change clears redo;
  changing creative direction or starting an AI turn clears manual history.
  Pending operations must finish before undo. Exported files remain on disk.

Under the viewer, **Manual tools** provides crop, resize, quarter-turn rotation,
horizontal/vertical flips, text, arrows/shapes and censoring without an AI call.
Geometry uses nearest-neighbor pixels, with a 1000-pixel working-size limit.
The original images remain in the project.

The **Materials** tray searches project images and saved characters/materials.
Use a selected image as subject, background or prop. Manual composition uses those
recorded roles; layout image slots also accept material thumbnails by drag/drop.

**Projects** opens the project home with previews and search for up to 20 recently
saved or opened projects. Missing files are marked unavailable; Open project file
can locate a moved file. Removing an entry leaves the file untouched. Opening a
project asks how to handle unsaved work. Recovery from the previous run is available
in the home as well as the recovery banner.

New saves use project format 4. This version still opens formats 1–3 with correction
controls defaulted off. Older releases cannot open new format-4 saves.
