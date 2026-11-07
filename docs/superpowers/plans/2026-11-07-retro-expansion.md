# Retro expansion implementation

Baseline: `361a0ef`; reuse the research worktree. The existing untracked research report is inherited from the preceding research task. Preserve it. No other inherited source changes.

Implement the recommended expansion in dependency order, including distinct application skins. Retired APIs and integrations whose published rules conflict with saved projects remain excluded as specified in the research.

## Acceptance criteria

- Choose an interface skin (classic desktop, terminal, GeoCities, Y2K, paper, or existing light/dark/system): controls remain readable, keyboard focus visible, settings persist after reload, and picture pixels stay unchanged. Density, text size and reduced motion work with every skin.
- Browse all creative directions, filter/favorite them, preview deterministic examples, select a supplied image and create a real editable layout. Exact-size badges remain exact-size. New directions have usable layout/assets, not only prompt labels.
- Adjust creative defaults and project overrides, save/reopen and switch branches: resolved choices and old tool parameters survive. Unsupported values fail without losing work.
- Use additive canvas, palette, bitmap text, pattern and animated-composition tools through the registry, UI, CLI and MCP. Hard masks, nearest scaling, explicit seeds, bounded frames/memory and deterministic output are preserved.
- Configure and select source profiles; filter searches; import selected collection/archive/IIIF/palette material with provenance. Partial failures preserve successes, credentials stay out of projects/logs, unsupported services are not advertised as ready.
- Disable remote sourcing consistently across tool routes. Local-only sessions refuse remote providers and missing downloads. Saved imported pixels replay offline.
- Use export presets and size constraints, save recipes with exposed knobs, compare branches, and run bounded batches. Cancel preserves completed steps and outputs; files never silently overwrite.
- Keep asset packs declarative and versioned, with credits and validation. Expose source-role pins, saved searches, favorite briefs and history controls without automatically sending private folders to a provider.
- Run affected quick and browser checks. Retain logs, screenshots and summaries. Exercise native checks only where the host supports them and report unavailable coverage honestly.

## Work sequence

1. Establish isolated dependencies and baseline checks.
2. Theme and accessibility system; settings and project persistence.
3. Shared style catalog, retro layouts/primitives, packs and visual browser.
4. Source profiles, adapters/importers, provenance and source controls.
5. Recipes, batches, comparison, export/credits and storage controls.
6. Integration tests, visual review, fixes and user documentation.

Progress is recorded here as work completes; an unchecked item is not a delivered feature.
