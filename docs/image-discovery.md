# Finding images and keeping creative directions

Open **Images & directions** in the desktop header. The new tools also appear in the manual tool
palette, CLI, and MCP registry.

## Find images

Enter the subject, its role (head, subject, background, prop), and optional pose/expression. Search
returns a numbered contact sheet and small previews. Only the sheet enters the session; **Use image**
imports the selected image with its source page, creator, and supplied rights information.

**More pictures of this exact subject** resolves the named Wikipedia article's Wikidata Commons
category, with a quoted Commons search fallback. It avoids treating related articles as alternative
photos of the same person. Categories can still contain irrelevant pictures; inspect the sheet.
**More like this** and **Different view** compare the candidate's preview with new results.

Ranking uses keyword relevance, image shape, detected face size for head swaps, quiet caption
margins, and perceptual similarity. Near-duplicate filtering compares coarse image structure and
color. It does not identify people or reliably recognize expressions or pose; the vision-capable
art director must inspect those. Small preview dimensions are not original-image dimensions.

Default collections are Commons, Openverse, Library of Congress, The Met, NASA, Cleveland Museum of
Art, and Wellcome Collection. None of these require an API key. Failed sources
leave successful candidates available and report their failures. Library of Congress searches its
photo catalog, not only its Free to Use sets; inspect each item's rights information. The Met adapter
selects public-domain images. NASA and other sources can have item-specific restrictions; unavailable
rights remain unknown rather than receiving an invented license.

Cleveland adds CC0 paintings, prints, sculpture, costumes, and objects. Wellcome adds historical
posters, illustrations, photographs, and scientific imagery with image-specific reuse information.
See [key-free collections and source status](open-collections.md) for their image choices and limits.

Optional sources are configured in the **core process environment**:

- `BADSHOP_FLICKR_API_KEY`: enables Flickr Commons search.
- `BADSHOP_SMITHSONIAN_API_KEY`, `BADSHOP_BHL_API_KEY`, and `BADSHOP_EUROPEANA_API_KEY`:
  enable the [additional archive and museum collections](collections-and-pairing.md).
- `BADSHOP_IMAGE_SEARCH_URL`: enables a user-operated HTTPS image-search gateway. It must have no
  embedded credentials, query string, or fragment. badshop sends `GET ?q=WORDS&limit=N`. Return
  `{"results":[{"url":"https://…","thumbnail":"https://…","title":"…","page":"https://…","license":"…","creator":"…"}]}`.
  Only `url` is required. The gateway manages any upstream search-provider authentication.

These values never become tool parameters or project credentials. Optional collections and the custom
gateway are included in **All public collections** only when configured. Live search is inherently variable;
selected imported images are stored in the project for replay.

The optional [Chromium browser helper](../browser-extension/README.md) copies the exact selected
image URL and source page. Paste its card into chat or the image-URL field. Ordinary image URLs work
in that field too. The helper is a local extension, not a browser-store release.

## Junk drawer

Select an image in the viewer, name it, and add comma-separated tags. The drawer persists separately
from projects in the badshop application data directory. It keeps the chosen image, its available
original/source, and reusable crop/face metadata. **Use image** imports it into the active session,
attaches it to chat, and makes its tags and metadata available to the art director. Renaming and
retagging change the drawer entry; removing an entry leaves existing project images intact.

## Branches

Create a named branch from the current state or a finished step. Switching stores the outgoing
branch before restoring the selected timeline. Save the project to preserve every branch together.
Branches share immutable image bytes but keep distinct tool histories and conversations. Running
turns and pending approvals must finish or stop before switching.

Project schema 2 adds branch snapshots. Existing schema-1 projects load automatically; older
badshop versions cannot read newly saved schema-2 files. Back up a project before opening it in
an older installation.

For six composition styles, three separate takes, bounded visual checks, and reproducible human
comparisons, see [creative evaluation](creative-evaluation.md).
