# BadShop styles sources and settings research

November 7, 2026

BadShop should expand through complete, recognizable internet styles, better control over its existing image collections, and reusable creative defaults. The highest-value first release combines a visual style browser, eight finished starter directions, source profiles, and export presets. Follow it with animated stickers, palette tools, and reusable recipes. Every composition continues through the deterministic engine; no image-generation model enters the pipeline.

This proposal covers BBS graphics, the amateur web, Y2K, forums, social profiles, early memes, and later remix cultures. Priority and effort ratings are product judgments. API availability and restrictions reflect the cited documentation checked on November 7, 2026.

## What already exists

The implementation is substantially beyond the original September design spec. Avoid spending another milestone rebuilding features already present.

| Area | Current implementation | Useful next addition |
| --- | --- | --- |
| Creative directions | Six shared recipes: forum signature, WordArt disaster, tabloid, bootleg DVD, museum vandalism, conspiracy diagram | Searchable visual catalog, era tags, favorites, explicit controls, more coherent recipes |
| Layouts | Sixteen deterministic formats, including comic, trading card, inventory, newspaper, desktop error, ticket, menu and product box | Internet-specific layouts: homepage, forum post, instant message, profile, demotivator and tiny badge |
| Asset packs | Eight procedural packs, four decorations each; `.badpack` import/export | More varied assets per theme, native tiny dimensions, pack previews and versioned dependencies |
| Sources | Twelve adapters: Commons, Openverse, LOC, Met, NASA, Cleveland, Wellcome, Flickr Commons, Smithsonian, BHL, Europeana, custom gateway | Source selection profiles, filters, credentials UI, incremental results and better source health |
| Other acquisition | Wikipedia, Twemoji, Imgflip, URLs, clipboard and browser source cards | More graphic libraries, selected archive imports and IIIF manifests |
| Local material | Explicit folder indexing, GIF/video frames, PDF/scan pages, sprite-sheet slicing | Better tagging and saved searches; animation-preserving compositing |
| Creative iteration | One or three takes, branch snapshots, junk drawer, image pairing, novelty controls and local idea mixer | Visual branch comparison, favorites, saved mixer locks and reusable parameterized recipes |
| Settings | Provider setup, approval mode, replay, output folder, step budget, timeout, memory and theme | Creative defaults, source profiles, export profiles, cache controls and motion preferences |

The mixer currently has six broad eras, only two directly centered on home computers and forums. Source credentials are primarily environment variables. Theme is saved separately in browser local storage; core settings use an atomic JSON file. `sources.status` reports configuration presence, not whether a service or credential actually works.

Repository evidence: [creative catalog](../../core/src/badshop/agent/creative_styles.json), [layouts and packs](../layouts-and-packs.md), [image discovery](../image-discovery.md), [local media](../local-media.md), [idea mixer](../idea-mixer.md), [novelty](../novelty.md), [settings model](../../core/src/badshop/server/settings.py), [settings UI](../../app/src/components/Settings.tsx), and [source adapters](../../core/src/badshop/engine/discovery.py).

## Organize styles around recognizable artifacts

An era label alone does not specify a composition. A 1998 fan page, a 2004 forum signature, and a 2006 glitter greeting need different dimensions, typography, decoration and motion. Let users choose a recognizable artifact first, then adjust era, density and finish.

Historical anchors should guide the art direction. Sixteen Colors preserves the ANSI/ASCII artpack tradition associated with BBS culture. Olia Lialina describes the amateur web as a distinct visual culture, including wallpaper and construction imagery. Cameron's World demonstrates how varied GeoCities material was. These references support distinct families rather than one generic retro filter. [Sixteen Colors](https://16colo.rs/), [A Vernacular Web](https://art.teleportacia.org/observation/vernacular/), [Cameron's World](https://www.cameronsworld.net/).

Use the following as a proposed creative taxonomy, not a claim that each style belongs exclusively to one date or community. “Existing base” means ingredients are present; it does not mean the finished preset is implemented. P1 is the first expansion, P2 follows shared primitives, and P3 is exploratory.

| Style family | Visible result | Existing base and required addition | Priority |
| --- | --- | --- | --- |
| BBS ANSI art | Block lettering, limited colors, textmode borders and a ridiculous login screen | New bitmap text/cell renderer; original artpack-inspired assets | P2 |
| ASCII and IRC transcript | Monospace exchanges, emoticons, nicknames and box-drawing characters | New transcript layout and deterministic glyph coverage | P1 |
| One-bit desktop / HyperCard | Black-and-white stipple, card borders and chunky icons | Desktop layout base; add ordered dithering and bitmap font | P2 |
| GeoCities fan page | Tiled stars, giant welcome title, portrait, divider, guestbook and counter | Existing homepage pack; add full layout and repeatable wallpaper | P1 |
| 88×31 web badge | Tiny beveled button with two-frame text or icon changes | New exact-size layout; existing animation can assemble prepared frames | P1 |
| Blinkies and pixel stamps | Narrow flashing declarations and collectible tiny stamps | New tiny layouts and original ornaments; richer animation later | P2 |
| Web portal / search directory | Dense categories, sponsored boxes and absurd search results | New structured layout; all links are decorative output pixels | P2 |
| Y2K cyber flyer | Metallic-looking lettering, bubbles, starbursts and strange futuristic slogans | WordArt base plus opaque graphic assets and new title treatment | P2 |
| Winamp-style skin | Compact player, equalizer bars, playlist and tiny labels | New player layout with original chrome; no executable skins | P2 |
| Windows 95/98 desktop chaos | Error boxes, taskbar, file icons and overlapping windows | Existing desktop-error layout; extend to bounded window stacks | P1 |
| AIM / MSN / ICQ-style chat | Buddy list, away message, timestamps and crude emoticons | New messenger layout and original status icons | P1 |
| phpBB / vBulletin-style post | Avatar, username, post count, quote box and huge signature | New post layout; reuse forum-signature recipe | P1 |
| Clan banner and userbar | Narrow strip, mascot, rank insignia, name and scanlines | Existing forum style; add banner/userbar dimensions and hard stripe pattern | P1 |
| MySpace-style profile | Portrait, interests, friends grid, decorative song-player box | Existing grid layouts; new profile composition | P2 |
| Glitter greeting / Blingee-inspired | Hard glitter border, butterflies, hearts and moving sparkle pixels | Existing sparkle/animation base; add bounded animated ornaments | P2 |
| LiveJournal icon / dollmaker scene | Tiny portrait, emotional caption, wardrobe or room cutouts | New icon presets and licensed/original dress-up assets | P2 |
| Flash portal / sprite comic | Loud menu buttons, game panel or dialogue between cutout sprites | Existing comic and sprite slicer; add portal layout and speech balloons | P2 |
| LOLcat and advice animal | A subject, very short top/bottom captions, optional radial background | Existing Impact tool; new original radial canvas and recipe | P1 |
| Demotivational poster | Black surround, inset picture, grand title and dry subtitle | New frame layout using existing images and text | P1 |
| Rage comic | Simple expressions, four panels and blunt dialogue | Comic base; four-panel layout and original/licensed expression pack | P2 |
| Imageboard greentext | Sparse text, green quote lines, small image and exaggerated story | New text layout; original fictional post framing | P2 |
| Web 2.0 / Frutiger Aero parody | Grass, sky, shiny-looking badges, optimistic corporate messaging | Source photos and opaque sticker shapes; no added alpha blending | P2 |
| Early video tutorial screenshot | Tutorial title, cursor, annotations and recorder mark | Existing watermark/draw tools; player frame and cursor pack | P1 |
| Repost chain / deep-fried meme | Recompression, repeated captions and accumulated recorder marks | Existing finish tools; explicit chain recipe with readable limits | P1 |
| Tumblr / vaporwave collage | Statue, computer window, tiled composition and deliberately dated text | Existing cutouts/layouts; themed asset selection and new layout | P2 |
| Webcore / dreamlike desktop | Empty rooms, misplaced UI, blunt text and mismatched imagery | New direction recipes using existing sources and hard pasting | P3 |
| Nokia LCD / early phone screen | Monochrome display, tiny menu, signal/battery indicators | New phone-screen layout, bitmap glyphs and fixed palette | P2 |
| Teletext and local cable listing | Block colors, page number, schedule and over-serious announcement | Existing cable pack; teletext grid and glyph renderer | P2 |

CARI's Y2K and Frutiger Aero collections are useful visual references. Its site explicitly presents the images for research rather than as a free asset library. Re-create the motifs with original graphics and properly sourced photographs. The Winamp Skin Museum is likewise a reference and selected-import opportunity, not a blanket redistribution license. [Y2K reference](https://cari.institute/aesthetics/y2k-aesthetic), [Frutiger Aero reference](https://cari.institute/aesthetics/frutiger-aero), [Winamp Skin Museum](https://skins.webamp.org/).

### Eight complete starter directions

Ship an initial set that demonstrates different compositions: **GeoCities fan page, forum post with signature, instant-message conversation, desktop error pile, 88×31 badge, demotivational poster, LOLcat/advice animal, and early video tutorial screenshot**. ASCII transcript and clan userbar can follow immediately as small extensions.

Each direction should include a deterministic preview, a complete layout, a small original asset set, one example brief, meaningful controls, and a clean-base recipe. A long list of prompt labels without these ingredients will produce less reliable differences between outputs.

Suggested controls are deliberately concrete: background tile, title, screen name, caption slots, decoration count, outline width, JPEG passes, palette size, frame delay and seed. Start at a restrained default. “Make it worse” can expose stronger values, while the chosen subject and joke remain legible.

## Add a few shared pixel primitives

Extend the registry with additive tools or layout capabilities. Leave the reference engine's algorithms and existing defaults intact.

| Primitive | What it unlocks | Contract |
| --- | --- | --- |
| Canvas and tiled background | Homepages, badges, radial meme backgrounds | Explicit width/height, solid fill or image tile, integer spacing and offset; bounded dimensions |
| Frame and panel decorations | Demotivators, forums, profiles, messenger windows | Named border geometry and padding; emit slot/caption metadata; preserve image references |
| Fixed palette and ordered dither | ANSI-like colors, one-bit cards, handheld displays | Explicit color list and dither mode; deterministic mapping; a new tool preserves old GIF behavior |
| Bitmap text | Tiny badges, BBS, teletext, chat and phone screens | Versioned redistributable font; integer scale; missing-glyph detection; explicit overflow behavior |
| Repeated graphic pattern | Scanlines, checkerboards, glitter borders, wallpaper | Binary coverage masks, integer placement and seed; no soft composite edges |
| Animated sticker composition | Moving stars over a still photo; blinking ornament border | Frame-wise hard compositing, explicit timeline and bounded frame budget |

The animation task is larger than adding a GIF search source. The app already records frame counts and can make sequences, but ordinary static image operations do not establish support for preserving several independently timed animations. New composition must handle input frame disposal, frame duration, looping, transparency and output palette behavior. Use a bounded output duration and time sampling rather than the least common multiple of every input loop, which can explode.

A reasonable initial motion preset is a two-second loop at 100 ms per frame, with a proposed maximum of 60 output frames and three animated ornaments. Validate these limits against memory measurements before shipping. Preserve input bytes and resolved timing in the project. Preview playback must be independent of export settings; pausing the viewer must not alter the saved GIF.

Lospec supports retrieving individual palettes by slug, including their name, author and color values. A palette import fits this workstream; it is not a replacement image search service. Store the actual color array for replay. [Lospec palette API](https://lospec.com/palettes/api).

## Image source priorities

BadShop already has broad museum coverage. New sources should add a different kind of usable material or reduce acquisition friction. Treat three questions separately: can the service be queried, can the selected pixels be retained for projects, and what rights information accompanies the image?

### Sources and libraries worth pursuing

| Source or route | Unique value | Access and retention implications | Recommendation |
| --- | --- | --- | --- |
| Original procedural packs | Construction signs, counters, avatars, smileys, pointers, borders and tiny UI | Existing local pack machinery; no search key or external image download | Highest priority; extend the current eight packs with complete visual systems |
| Art Institute of Chicago | Paintings, prints, objects and unusually expressive historical subjects | No API authentication; documented public-domain filter and IIIF images; anonymous limit is 60 requests/minute | Best next dedicated museum adapter; require `is_public_domain` and an image ID. [API docs](https://api.artic.edu/docs/) |
| Kenney packs | Game UI, props, icons, tiles and sprites | Asset-page game assets are CC0; downloadable packs fit the junk drawer and sprite slicer | Curate optional versioned `.badpack` conversions, preserving the included license. [Kenney support](https://kenney.nl/support) |
| OpenMoji | Another coherent emoji/icon visual vocabulary | PNG/SVG releases; graphics are CC BY-SA 4.0, code has a separate license | Optional frozen PNG pack; retain attribution and share-alike information. [Project and license](https://github.com/hfg-gmuend/openmoji) |
| Game-icons.net | Silhouettes for inventories, achievements, absurd signs and badges | Project states most icons are CC BY 3.0, with some public-domain contributions | Curated pack with per-icon creator/license records; build PNG assets ahead of distribution. [Contributor licensing](https://github.com/game-icons/icons/blob/master/CONTRIBUTING.md) |
| Generic IIIF manifest import | Pages, posters, maps and object images across institutions | A protocol for media/metadata, not a license or global search engine | High-value second-stage importer; accept a manifest URL and let the user choose a canvas. [IIIF Presentation 3](https://iiif.io/api/presentation/3.0/) |
| Internet Archive selected items | Scans, advertisements, manuals, screenshots and ephemera | Documented item metadata/file interface; rights vary by item; some files are restricted | Start with a pasted item URL and chosen file/page; then consider bounded collection search. [Metadata API](https://archive.org/developers/md-read.html) |
| GifCities | Authentic old-web GIF reference and selected source material | Website exists, but this research received a rate-limit response; a supported integration contract remains unestablished | Browser-assisted selected import first; do not promise a stable search adapter. [GifCities](https://gifcities.org/) |
| Rijksmuseum | Prints, objects and Dutch art, with richer collection metadata | Current data services provide APIs and downloads; implementation must follow the present service model and item rights | Later adapter or IIIF route; overlap with current museum sources lowers urgency. [Data services](https://data.rijksmuseum.nl/) |
| Pexels | Mundane rooms, objects and stock-photo expressions missing from archives | Keyed photo API; service attribution; currently 200 requests/hour and 20,000/month by default | Optional stock source after credential UI; review retained-image workflow against current content/API terms. [Documentation](https://www.pexels.com/api/documentation/) |
| Pixabay | Clip-art-like illustrations and ordinary stock backgrounds | Keyed API; request caching for 24 hours; no systematic mass downloads; selected images should be downloaded rather than permanently hotlinked | Optional later source with its own cache policy and item provenance. [API rules](https://pixabay.com/api/docs/) |
| Brave Image Search through the existing gateway | Topical and obscure subjects absent from public collections | Keyed image-search API; language/country controls; search results do not confer reuse rights | Document a gateway adapter first; assess subscription terms and project retention before a native integration. [Image search docs](https://api-dashboard.search.brave.com/app/documentation/image-search) |

For Chicago, use bounded image sizes appropriate to the working copy and honor the museum's guidance on serial image downloads. The current shared preview pool is concurrent, so adding an adapter requires a per-origin request limiter, not only another function in `SEARCHERS`. Keep API request limits separate from image-host limits. [Chicago image and request guidance](https://api.artic.edu/docs/).

Internet Archive requests also need appropriate identification and backoff. Its current developer guidance specifies descriptive User-Agent information and respecting `Retry-After`. Selected files still need item-level rights and availability checks. [Automated access guidance](https://archive.org/developers/bots.html).

### Tempting integrations to defer or exclude

| Candidate | Evidence | Decision |
| --- | --- | --- |
| Tenor API | Google says new integrations stopped in January and all API integrations were decommissioned June 30, 2026. [Official notice](https://support.google.com/tenor/answer/10455265?hl=en) | Exclude from the roadmap |
| NYPL Repo API | Official documentation says it became unavailable August 1, 2026, with no public replacement planned there. [Deprecation notice](https://api.repo.nypl.org/) | Exclude the old adapter; other visible NYPL endpoints require separate support/terms verification |
| Artsy public API | Its developer page warns the public API is retiring and may disappear without notice. [Developer notice](https://developers.artsy.net/) | Exclude as a new dependency |
| GIPHY | Published integration rules prohibit caching/storing media, proxying requests and mixing providers in one grid. [Integration rules](https://developers.giphy.com/docs/api/#best-practices) | Poor fit for immutable project storage and mixed-source discovery; require an explicit compatible agreement before integration |
| Unsplash API | Requires hotlinked images, download event reporting, attribution and confidential application keys; says apps should not require users to register developer accounts. [API guidelines](https://help.unsplash.com/en/articles/2511245-unsplash-api-guidelines) | Defer: desktop-only key distribution and offline replay need an approved design, not a generic bring-your-own-key adapter |
| Unlicensed GIF, sticker, skin and sprite dumps | Public visibility and an archive copy do not establish a redistribution grant | Use creator-authorized packs or selected imports with accurate provenance; do not bundle a scraped archive |

A browser import is an acquisition mechanism, not a way to bypass a provider's integration or content rules. Preserve “unknown rights” when appropriate. Do not label a search result “safe for commercial use” merely because it came from an open collection.

### Improve existing discovery before adding many adapters

The current `all` mode searches every configured source, fetches bounded previews and ranks a shared result set. More adapters increase latency and may crowd out useful categories. Add named source profiles such as **Historical people**, **Paintings and weird objects**, **Stock-photo nonsense**, **Old-web graphics**, and **My local junk**. Users should see the member sources and be able to edit them.

Expose source subsets, licensing preferences, orientation, minimum original dimensions where known, media type and language. Use date as a filter only when the underlying metadata supports it; an upload date is not the depicted era. A source without a requested filter must show that limitation rather than silently ignoring it.

Openverse already documents filters such as source, license, license type, extension and mature content. The current adapter supplies only query, page size and `mature=false`. Extend the existing route instead of presenting Openverse as a new source. Precise filter names and authentication limits should be contract-tested against its current consumer API when implemented. [Openverse API reference](https://api.openverse.org/v1/).

Show results as individual sources finish, with stable candidate IDs and a final frozen ranking. Preserve the current partial-success behavior. Add **More from this collection**, **Same creator**, **Save this search**, **Hide this result**, and a clearer **Use as subject/background/prop** action. Existing similarity and same-subject controls remain useful; their heuristics must not be advertised as identity or pose recognition.

## Settings worth adding

Put creative choices beside the chat and preview. Put persistent defaults and connections in Settings. Ordinary output controls belong to an export profile. Avoid forcing people through a large settings dialog for each picture.

The following defaults are proposed. “Project” values travel with the project and branch snapshot; “App” values affect future work on that machine. Explicit tool parameters always win over defaults.

| Setting | Proposed default | Scope and visible behavior |
| --- | --- | --- |
| Favorite styles and recent styles | No preselected favorite | App; quick style access without scrolling the whole catalog |
| Default style | None | App default copied into a new brief; never restyles an open project |
| Era strictness | Loose | Project; Strict favors matching fonts/assets/format and marks deliberate anachronisms in the brief; no historical-accuracy guarantee |
| Decoration density | Medium | Project; maps to visible ornament count, occupancy and size, not an unspecified prompt adjective |
| Caption policy | Short captions | Project; allows None, Short, Exact text; exact text overflow is reported rather than silently rewritten |
| Subject and layout locks | Supplied subject locked | Project; preserve selected input artifacts and slot choices across takes |
| Default number of takes | One | App default; preserve the existing three-take option and its step-budget limit |
| Randomness | New seed per new take | Project/step; display seed, allow lock/shuffle, and persist resolved values |
| Enabled sources and source profile | Existing key-free collections | App plus project preference snapshot; no hidden new network destination on project open |
| Source credentials | Keychain or environment reference | App only; no secret in project, pack, tool parameters, logs or exported diagnostics |
| Source connection test | Manual | App; separate Not configured, Configured, Last succeeded, Unauthorized and Rate limited; timestamp health |
| Rights preference | Prefer explicitly licensed material | Project; offer strict CC0/public-domain and permissive discovery modes, with unknown rights shown distinctly |
| Search language | Current English behavior | Project; passed only where supported; preserve original query alongside any translated query |
| Source content filtering | Preserve current source defaults | App/project; show per-source capability rather than implying universal filtering |
| Search breadth | Eight selected candidates | Project; keep bounded requests; explicit More results action instead of unbounded agent retries |
| No remote image sourcing | Off | App/session; block search/fetch/download paths consistently while local imported assets remain usable |
| Export profile | Existing finish behavior | App default resolved into explicit step parameters; presets for forum JPEG, tiny badge GIF, limited-palette GIF and PNG |
| Target file size | Off | Export; bounded attempts, visible final dimensions/quality/bytes and an honest failure when the target cannot be reached |
| Animation preview | Follow system motion preference | App; pause/play/step controls; does not change output pixels or GIF timing |
| Animation default timing | 100 ms per frame for new presets | Project/step; imported timing preserved unless explicitly resampled |
| Font fallback | Bundled known font | Project/step; record actual face/version; missing font produces an actionable message and explicit fallback choice |
| Cache budget | Proposed 512 MiB for disposable cache | App; show usage and clear previews separately from project assets and junk drawer |
| Creative history | Preserve current bounded history | App; add retention choice and “don't record this session”; existing Forget action remains |
| Interface density and text size | Current density, 100% text | App; keyboard navigation and reduced motion survive every cosmetic theme |

“No remote image sourcing” is more precise than “offline mode”: a cloud art director can still receive selected images. A separate **Local-only session** should validate that the chosen provider is local and all required assets are installed, then refuse remote provider and download operations. Neither label should silently fall back to the other behavior.

Keep the working-coordinate ceiling unchanged in this release. Arbitrary working-resolution settings would affect layout dimensions, cached steps, memory use and replay. Tiny exact-size exports are compatible; a high-resolution editing mode requires its own design.

A deliberately retro application skin can be a later cosmetic choice—classic gray, terminal or early-web accents—but it should not change tool behavior or make text hard to read. Output style and application theme are separate concepts.

### Persistence and failure rules

Apply precedence as **explicit tool parameters → saved project choices → app defaults**. Resolve defaults before recording a step. Changing the default JPEG quality or installed style version must not change an old project's replay.

Record style ID/version, layout ID/version, pack asset hashes, selected font identity, explicit seeds and resolved parameters. Save global settings atomically. Invalid fields produce clear validation errors without discarding unrelated valid values. Canceling a source login, import, pack installation or export leaves the current project intact.

New per-project creative fields must also be included in branch snapshots. The current project schema is 2, so schema changes need migration and round-trip coverage. Source keys and private endpoints remain machine-local; opening a shared project does not install credentials or enable a new source.

## Other features with a strong fit

| Feature | Concrete user benefit | Implementation direction |
| --- | --- | --- |
| Style browser with previews | Recognize the difference between fan page, clan banner and glitter card before using a model | Generate previews from fixed fixtures with the real engine; filter by era, format, motion and installed assets |
| Saved recipes with exposed knobs | Reuse a successful joke with a new subject, title or caption | Declarative steps with typed substitutions; expand into ordinary editable timeline steps |
| Compare branches and takes | Choose a favorite without remembering which artifact belonged to which take | Side-by-side final outputs, seed/source differences and branch labels; build on existing branches |
| Small batch queue | Make several captions or badges from the same inputs | User-supplied rows, fixed maximum count, per-item status, Stop after current safe point, preserve completed outputs |
| Source tray by role | Keep donor heads, backgrounds, props and decorations organized | Store role metadata and pins; feed selected roles to the existing pairing tool |
| “Make this worse” controls | Increase badness predictably without losing the premise | Expose stretch, oversize, cutout halo, JPEG passes, duplication and typo choices; start from a selected clean branch |
| Credits export | Keep source information attached to a finished collage | Walk artifact/step ancestry and emit a credits text/JSON sidecar; unknown rights stay unknown |
| Exact-size output presets | Produce a usable avatar, web badge, blinkie or signature immediately | Integer dimensions and nearest-neighbor scaling; file-size display; original remains stored |
| Persistent idea-mixer locks | Return to the same combination of era, setting and format | Save user-selected locks and favorite briefs; unify style IDs with the core catalog |
| Pack manifest with previews and compatibility | Know what a pack contains and whether its recipes will run | Add version/dependency/rights metadata; frozen images and declarative recipes only, no arbitrary code |

Do not add auto-posting, accounts, cloud asset hosting, executable plugin packs or manual pixel editing as part of this expansion. They create separate products and conflict with the existing scope. Read-only coordinate picking and editable parameters already provide the appropriate level of control.

## Architecture and implementation order

### Shared catalogs and stored recipes

Extend `creative_styles.json` with stable IDs, version, family, tags, preview artifact reference, layout dependencies, pack dependencies and supported controls. Keep human-readable direction fields, but inject only the selected direction and relevant alternatives into the agent context. Today every style is included in `direction_prompt`; expanding to dozens of full recipes would waste context and invite cross-style confusion.

Move era definitions toward a shared core catalog so the mixer, style browser and CLI agent use the same IDs. Preserve existing IDs and old messages. A renamed display label should not break a saved project.

Add layouts through `engine/layouts.py` and its registry/schema path. New tools belong in additive engine modules registered once for UI, CLI and MCP. UI catalog choices should come from capability data; they must not advertise a template or effect absent from the running core.

### Sources and provenance

The current candidate/source representation is small: kind, URL, page, title, license and creator. Add structured optional fields for origin service, origin item ID, exact rights URI/text, original dimensions when known, retrieval timestamp and availability of animation. Preserve raw source attribution separately from display cleanup. Do not use one loose license string as an automated legal verdict.

Introduce source capability metadata for authentication, supported filters, retention policy, attribution, content filtering and rate limits. Apply the same enable/disable rules to `discover`, legacy `fetch`, `wiki`, `template`, `emoji` and direct URL acquisition. A setting that disables discovery but permits the agent to fetch the same source another way is incomplete.

Treat generic IIIF manifests and archive metadata as untrusted structured data. Bound nested resources, pages, redirects, downloads and frame counts; follow the existing network policy for every referenced URL. Importing a manifest must never cause an unrestricted crawl. Store selected pixels so replay does not depend on a changing URL.

### Delivery sequence

Effort is relative: Small is a focused catalog/UI change using existing capabilities; Medium spans several core/UI/persistence paths; Large introduces a new rendering or execution model. These are not calendar estimates.

| Stage | Deliverable | Value / effort | Exit condition |
| --- | --- | --- | --- |
| 1 | Visual style browser, eight starter directions, original decorations and exact-size presets | High / Medium | Every direction has a visibly distinct reproducible fixture and editable steps |
| 2 | Source profiles, source credentials UI, filter capabilities, Chicago adapter and richer provenance | High / Medium | Search → select → save → reopen works; partial failures and missing keys remain useful |
| 3 | Kenney and icon packs, IIIF/selected archive import, saved searches and credits export | High / Medium | Selected assets work offline after import; credits and source metadata survive pack/project round trips |
| 4 | Bitmap text, fixed palettes, tiled backgrounds and animated ornaments | High / Large | Bounded deterministic output, timing/disposal coverage and paused-preview behavior verified |
| 5 | Saved recipes, comparison and small batch queue | High / Medium to Large | Batch cancellation preserves completed work; recipes remain ordinary inspectable steps |
| 6 | Expanded aesthetic catalog, optional stock/general web adapters and cosmetic app themes | Medium / Variable | Each addition demonstrates useful material or composition absent from earlier stages |

Stages are dependency groups, not a demand to finish all catalog work before adding a source. A narrow first implementation can combine one GeoCities layout, one forum-post layout, a style browser and source-profile controls; validate that vertical slice before multiplying presets.

## Acceptance criteria for implementation

| User action | Expected visible result | Persistence, failure and cleanup | Verification |
| --- | --- | --- | --- |
| Choose a style and use a supplied photo | Recognizable layout, selected subject, readable caption and visible tool steps | Save the resolved direction; missing dependency names the required pack | Core fixture plus real UI/core browser workflow |
| Change density or caption after rendering | Only the intended parameters change; downstream outputs replay | Original branch remains available; no hidden re-fetch | Session replay and browser edit workflow |
| Change app defaults then reopen an old project | Existing result and replay stay unchanged | Defaults apply to future work; project snapshot wins | Project round trip with byte comparisons |
| Disable a source and request it through the agent | Clear unavailable-source result | No request through legacy or direct routes; no silent fallback | Network boundary tests and scripted agent |
| Search while one source returns 429 or fails | Successful candidates remain selectable; failing source is identified | Respect backoff; no retry storm or leaked key | Recorded API fixtures; separate bounded live smoke |
| Acquire a collection image and reopen offline | Selected source pixels and attribution remain available | Removing disposable cache does not break the project | Real acquisition smoke then isolated offline replay |
| Import a pack with a missing font or unsupported version | Useful incompatibility message | No partial installation; existing junk drawer unchanged | Pack validation and UI import workflow |
| Add animated stickers and save/reopen | Correct frame order, duration and hard transparency | Explicit seed/timing retained; oversized animation rejected before exhaustion | Frame/disposal fixtures and browser playback |
| Enable reduced motion and open animated output | Still preview with clear play/step controls | Export bytes unaffected by preview preference | Browser behavior and output hash comparison |
| Export an exact-size badge or target-size GIF | Correct dimensions and reported byte size | No overwrite; impossible size reports failure; cancel preserves work | Core export and native picker interaction |
| Stop a batch halfway | Completed outputs remain; queue marks unfinished items | Owned workers stop; temporary outputs cleaned | Session tests and desktop lifecycle checks |
| Save source credentials | Setup state updates and a test can run | Keys absent from project/pack/logs; keychain failure offers existing environment path | Isolated keychain/native integration, never user credentials |

Use `./verify.sh quick` for affected model/registry/session/UI contracts, `./verify.sh browser` for real frontend/core workflows, and `./verify.sh desktop` for Linux lifecycle work. On Windows, use the Python verification entry point documented in [development.md](../development.md). Native file dialogs, credential storage and motion behavior need their own actual platform interactions; browser fallbacks do not establish native coverage. Live source checks stay outside the quick suite.

Human evaluation should compare the same subjects across the eight starter styles and rate recognition, caption readability, stylistic distinctness and deliberate badness using the existing [creative evaluation workflow](../creative-evaluation.md). Do not turn those ratings into a claimed automatic humor score.

## Research record

Repository baseline: `361a0ef15e859360b1c16b4145a7607ad8a53079`. The source checkout was clean; the managed research worktree inherited no uncommitted changes. Scope is research and a proposal; no application behavior or engine algorithms were changed.

Research acceptance criteria: distinguish existing features from additions; cover all requested eras and adjacent cultures; check source access and constraints; define settings defaults and persistence; prioritize a practical delivery path; and supply user-action acceptance criteria. The tables above address those criteria.

Evidence consists of source inspection and primary public documentation. This is not a live integration or model-quality benchmark. GifCities returned a rate-limit page; direct Openverse documentation access was intermittently forbidden, although its indexed API reference was available. No authenticated source calls, provider calls, downloads of asset packs or application test suites were run. Documentation checks and their outcomes are recorded separately under `artifacts/verification/2026-11-07-feature-research/`.
