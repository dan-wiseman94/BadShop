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

## Delivered and verified

- [x] Isolated Windows and Arch Linux environments, with recorded source revisions and separate Python environments.
- [x] Six additional interface skins, density/text-size/motion settings, persisted project preferences, and schema-1/2 migration to schema 3.
- [x] Twenty-eight deterministic layout styles, eight registered tools, four original asset packs, and a visual style browser.
- [x] Chicago/OpenMoji and optional Pexels/Pixabay/Brave adapters; selected IIIF/Archive/Lospec browsing; source profiles, filters, keychain controls, local-only mode and credits.
- [x] Portable recipes, bounded cancellable batches, branch comparison, clean-base degradation, export presets and ancestry sidecars.
- [x] Focused Linux checks, real browser/core workflows, six-skin screenshot review, live public-source checks and user documentation.

At the user's request, merged `origin/main` through `5431062`, including PR #11's focused testing policy and PR #12's ownership/replay fixes. Removed tests stay removed. The autosave conflict preserves both retry-after-failure and creative-history controls.

Verification retained in `artifacts/verification/linux-merged/`: 54 retro/state-machine cases, 8 new-tool golden/coverage cases, 126 project/CLI persistence cases, 4 settings/protocol cases, 6 asset-status/path cases, 1 new-project pin case, and 16 frontend connection/mixer cases passed. Five selected real browser/core workflows are covered by four initial passes plus the corrected fresh-process journey; the original failed run remains recorded. The final theme workflow also passes after screenshot review. Lint, test collection and production build passed. `linux-premerge/` retains the earlier broad run, including its failed cases and passing native/launcher checks; it is not relabeled as a fully passing suite.

Verification found and fixed: transparent-GIF palette metadata, empty Lospec attribution, Windows-versus-Linux PNG encoding references (decoded pixels unchanged), batch cancellation ownership, cross-project image pins, theme-switch contrast, and a pre-existing model-runtime import in asset status that delayed shutdown. Existing pixel goldens are unchanged.

Boundaries: Kenney/Game-icons/GifCities/Rijksmuseum are collection links/manual imports. Keyed services and actual OS keychain integration were fixture-tested, not tested with live accounts. No installer was built or validated. The research report remains a broader backlog; speculative adapters, full curated third-party packs and other deferred ideas are not represented as shipped features.
