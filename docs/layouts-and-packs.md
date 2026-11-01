# Layouts and period asset packs

The **Layouts & packs** tab in Images & directions builds deterministic compositions with sixteen
layout formats: trading card, character select, two-panel conversation, newspaper front page,
supermarket flyer, game inventory, achievement popup, yearbook, certificate, classified ads,
sports scoreboard, desktop error dialog, cereal/product box, event ticket, tabloid cover, and restaurant menu.

The newer formats have their own visual structure and editable content:

| Format | Image slots and captions |
| --- | --- |
| Sports scoreboard | Two circular team images with large score fields and home/away labels. |
| Desktop error dialog | Error icon and message, a title bar and three decorative buttons. |
| Cereal/product box | Large front artwork and a side-panel badge, with facts panel and printed bars. |
| Event ticket | Event artwork, event details and detachable stub badge; a perforated divider. |
| Tabloid cover | Large lead image and headline, two smaller cover teasers, and a colored masthead. |
| Restaurant menu | Four circular dish images with wide description/price fields and menu dividers. |

Dialog buttons and printed barcode-like bars are decorative pixels. They do not perform actions or
encode ticket/product data.

Choose a template, assign session images to any slots, add captions and a title, and select
contain/crop/stretch fitting. Empty slots remain labeled placeholders. Expand each slot's coordinates
to move its image rectangle; the full layout stays editable through the timeline's `layout` step.
Images use nearest-neighbor scaling and thresholded alpha masks. Caption areas wrap and shrink text;
very long captions that cannot fit at the minimum size end in an ellipsis. Template sizes stay at
1000 pixels or less so subsequent tools use consistent working coordinates.

The same `layout` tool is available to the model, MCP, and CLI. `images` contains image references;
optional `image_slots` gives each image's zero-based slot number, allowing empty slots between images.
The result's `layout` data describes the canvas, image slots, hard masks, and caption regions.

Eight built-in packs each install four original procedural decorations in the junk drawer:

- School computer lab: gold star, A+ badge, praise badge, pointing arrow.
- 1998 personal homepage: construction sign, visitor counter, web-ring badge, email badge.
- Discount supermarket: sale burst, price badge, improbable deal, manager special.
- Cheap conspiracy documentary: evidence label, classified stamp, question label, red string.
- Bootleg gaming magazine: review badge, controller/player badge, exclusive badge, bonus badge.
- Local cable TV: live lower third, test pattern, channel bug, rabbit-ear television.
- Bargain-store packaging: nutrition panel, hanging clearance tag, prize burst, value-size bag.
- Office bureaucracy: rejected rubber stamp, manila folder, clipped memo, stapler.

They use geometric shapes and Pillow's bundled default font; no external artwork or image-generation
model is involved. Assets include center and bottom placement anchors, tags, and source credits.
Installing a pack adds entries; it does not modify the current composition.

Select saved library entries and **Export selected assets** to write a `.badpack` ZIP. It contains
`pack.json` and hashed image bytes under `images/`, including available originals and provenance.
An existing file is never overwritten. **Import asset pack** validates all metadata and image hashes
before creating new entries; existing library entries are kept. Packs support up to 100 assets,
20 MB per image, and 80 MB total image data. Unexpected members, traversal paths, symlinks,
encrypted entries, duplicate names, inconsistent image metadata, and unsupported pack versions are
refused. Imported metadata is still source data, not agent instructions.
