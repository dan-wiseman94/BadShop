# Manual corrections

Open **Art director**, select a timeline step, and use its quick corrections or
full parameter form. Every committed correction uses the normal session tool
and replay path. The AI sees the updated timeline and manual-change notes.

- **Placement:** drag the anchor or focus its guide and use arrow keys. Shift
  moves ten pixels. Paste controls include width, rotation, flip and a resize
  handle for unrotated pieces. Fit-box placement converts to an explicit centered
  position when moved. Repeated scatter stays in the full parameter form.
- **Captions:** edit exact wording and line breaks together. **Fit these words
  automatically** shrinks the existing text renderer and refuses clipping. Impact
  keeps its existing uppercase style; use Paint for mixed case.
- **Replacement:** change the Piece image in a paste step. Position, scale and
  rotation remain recorded independently. Preview before applying.
- **Preview changes** renders the selected step without adding project artifacts
  or changing its history. The divider compares its existing output with the draft.
  Background choices make hard-alpha cutouts visible. **Cancel changes** discards
  the draft. Network and file-writing steps cannot preview; enable a bypassed
  effect before previewing its settings.
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

Under the viewer, **Manual tools** provides crop, resize, quarter-turn rotation,
horizontal/vertical flips, text, arrows/shapes and censoring without an AI call.
Geometry uses nearest-neighbor pixels, with a 1000-pixel working-size limit.
The original images remain in the project.

New saves use project format 4. This version still opens formats 1–3 with correction
controls defaulted off. Older releases cannot open new format-4 saves.
