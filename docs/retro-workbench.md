# Retro workbench

Open **Images & directions → Retro workbench**. Choose an era or favorite a style, select an image in the viewer, enter a short title and build a layout. The result is an ordinary editable tool step. The browser includes 28 directions from BBS/teletext through GeoCities, desktop windows, messaging, forums, tiny buttons, comics, Aero, vaporwave and webcore. These are pixel interpretations, not replicas of proprietary applications.

**Settings → Preferences → Theme** has Classic Desktop, Terminal, GeoCities, Y2K, Paper and Arcade alongside system/light/dark. Density, text size and motion are independent. Reduced motion shows a still animation frame; Play preview and Next frame affect only the viewer.

## Creative choices and tools

Clutter, seed, image fit, exact captions, favorites, role pins, saved collection lookups, recipes and idea-mixer choices travel with the project. Branches snapshot their creative preferences. “Use these defaults for new projects” copies the creative defaults; image role pins stay with their original project. Existing tool parameters remain explicit. Project format 3 reads formats 1 and 2. Older BadShop releases cannot read newly saved format-3 projects.

New registered tools are available to the desktop, CLI and MCP:

| Tool | Purpose |
| --- | --- |
| `retro_layout` | 28 fixed-size compositions with named image slots in result metadata |
| `canvas` | Opaque colored canvas or hard-edged image tiling |
| `pattern` | Seeded stars, confetti, checks, grid and scanlines |
| `palette` | Mono, Game Boy, CGA, EGA, web or explicit custom colors; optional dithering |
| `bitmap_text` | Bundled 6×11 Latin-1 lettering at integer scale; exact mode rejects overflow |
| `animate_sticker` | Bounded GIF composition, blink/bounce/scroll, explicit uniform timing |
| `export_profile` | Exact dimensions and optional file-size ceiling |
| `collection_items` | Selected IIIF manifest, Archive item or Lospec palette browsing |

Boolean parameters defaulting to true have CLI `--no-…` flags, such as `--no-exact-text` and `--no-dither`. No image-generation service is used. Original engine algorithms and reference files are unchanged. New bitmap lettering is platform-independent; non-Latin-1 text should use the existing Text tool.

Four new built-in packs provide web buttons, blinkie labels, terminal tiles and homepage wallpaper. Pack exports declare their format/dependency version and carry each image's credits. Unsupported dependencies fail before installation. Packs contain frozen images, never executable plugins.

## Sources

Find images now includes Chicago and OpenMoji, plus optional Pexels, Pixabay and Brave adapters. Set their API keys under **Settings → Preferences → Sources, privacy and creative history**, or use the named environment variable. The OS keychain stores saved keys; projects only contain source metadata. Environment variables take precedence. Configured means credentials are present, not that a service or key has been tested.

Museum, icon/clip-art and photo/web profiles select discovery sources. Rights and orientation filters are local filters over returned metadata/previews, not legal determinations or guarantees of completeness. Sources can fail independently. Stock services keep their content licenses; Brave search does not grant image rights. Pixabay search responses cache for 24 hours, with a 512 MiB disposable-cache cap and a clear action. Cache cleanup excludes project images, the junk drawer and models.

The Sources panel browses one selected IIIF v2/v3 manifest or Internet Archive item at a time. Choose a file, review its source page, then import it. Lospec accepts a palette slug; applying it saves the actual colors in the tool step. Kenney, Game-icons, GifCities and Rijksmuseum are collection links for browser-selected downloads and local imports, not search adapters. They are not bulk crawled or automatically repackaged. Their assets still need the appropriate source and rights metadata.

Local only blocks tool downloads, asset downloads, cloud/custom/CLI model providers and allows chat only at a local-provider loopback address. Imported pixels can be reused offline. The discovery allowlist controls discovery searches; it is separate from the stronger Local only boundary. It does not firewall other applications on the computer.

## Recipes, comparison and export

Capture a completed local tool step in Recipes. New captures use version 2 with
separate named image roles (`$input:base`, `$input:piece`, or numbered slots), and
named text values (`$text:title`) with editable defaults. Earlier `$step0`,
`$step1` outputs can feed later steps. Version-1 recipes keep their `$input`
behavior; recapture a multi-image composition to give each image its own role.

**Save recipe** keeps the design in the project. **Save to design library** keeps
up to 50 designs in local settings for reuse across projects. Image roles are
chosen in the destination project; no old project image identifiers become defaults.
Each design can declare up to 32 roles and 40 steps. Text defaults travel with it.

Version-2 batches show editable rows with separate images and text. Each result
has its preview or error and a **Retry row** action. Batches allow up to 12 rows
and 60 total steps. Stop retains completed outputs and marks unfinished rows as
cancelled. Retrying a row creates new recorded steps without replacing previous
outputs. Network and file-writing tools are refused. Closing the app, losing its
last user connection or cancelling the request stops owned batch work.

Compare displays up to four branch results. The Export panel prepares 88×31 buttons, 150×20 blinkies, 500×150 signatures, 100×100 avatars or 1024×768 wallpaper. The source image remains stored. JPEG size limits try bounded quality values; PNG/GIF limits fail explicitly when the encoded result is too large. Export selected image + credits writes a unique image filename and JSON ancestry sidecar. Unknown creators or rights remain unknown.

Worse applies seeded deep-fry strength or repeated JPEG compression from the clean base you choose, so adjusting a setting does not accidentally compound the previous preview's damage.

The image export dialog also accepts custom dimensions (1–2000 pixels per side),
fit/crop/stretch, an opaque background, and a file-size limit in KB or MB. Optional
dimension reduction tries smaller nearest-neighbor outputs when the limit cannot
be met. Keeping animation produces GIF with per-frame timing and loop count;
animated preparation is limited to 200 frames and 20 million output pixels.
**Prepare and save** exports the newly prepared output. The preview reports exact
encoded bytes. Named export settings are saved across projects (up to 30 presets),
without retaining references to a project's images.
Choose up to twelve presets and **Prepare selected sizes** to create multiple
outputs from the same source. Each result has a preview and Save button. **Stop
after current size** keeps completed outputs. For an imported GIF's still working
copy, **Use animated original** selects its stored animation before exporting.

## Verification scope

Fixtures cover deterministic output, hard transparency, bitmap overflow, palette membership, animation trails/timing, exact-size limits, schema migration, branch preferences, batch cancellation, source metadata, keychain isolation, cache behavior and credential stripping on redirects. Browser tests exercise the real Python core, saved projects and theme persistence. Paid/keyed services require a configured account for live validation; fixture success does not establish live service availability. Native lifecycle smoke uses the isolated Arch WSL toolchain and private Xvfb; it is not installer coverage.

On 2026-11-07, the merged version passed focused core, project, settings, connection and browser checks. Live public-source checks passed for Chicago, OpenMoji, a selected IIIF manifest and Lospec; acquired Chicago/OpenMoji images survived saved-project reopening and offline replay. The pre-merge native window and launcher checks passed. The new project journey exposed an existing cold model-import delay during shutdown; asset status now locates the pinned model files without importing the model runtime, and the fresh-process journey passes. Logs, failure history and screenshots are retained under `artifacts/verification/`.
