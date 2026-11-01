# More collections and compatible image pairs

The discovery collection selector includes three additional sources. Configure their keys in the
core process environment; the keys never appear in tool arguments or saved projects. **All public
collections** includes these sources only when configured.

| Collection | Environment variable | What discovery selects |
| --- | --- | --- |
| Smithsonian Open Access | `BADSHOP_SMITHSONIAN_API_KEY` | Images whose individual media record says CC0, preferring original JPEGs and separate thumbnails |
| Biodiversity Heritage Library | `BADSHOP_BHL_API_KEY` | Pages marked Illustration, Map, or Foldout in up to four matching books/articles |
| Europeana | `BADSHOP_EUROPEANA_API_KEY` | Image records with media and open-reusability filters, retaining each item's rights statement |

Register keys through [api.data.gov for Smithsonian](https://api.data.gov/signup/),
[BHL](https://www.biodiversitylibrary.org/getapikey.aspx), and
[Europeana](https://pro.europeana.eu/page/get-api). BHL pages keep their original book/article title,
page number, source-page address, author, and available rights information. They can be imported as
whole pages and cropped into reusable illustrations. Page annotations are incomplete in some books,
so a matching book may yield no illustration candidates.

Implementation references: [Smithsonian's official client and API links](https://github.com/Smithsonian/smithsonian-openaccess),
[BHL API v3](https://www.biodiversitylibrary.org/docs/api3.html), and
[Europeana Search API](https://europeana.atlassian.net/wiki/spaces/EF/pages/2385739812/Search+API).

## Pair images

Open **Images & directions → Image pairs**, select donor and background images, then choose
**Compare image pairs**. Inspect the previews and choose **Compose this pair** to add an editable
paste step and attach its result to chat.

The `pair_images` tool compares up to six donor images with up to six backgrounds and returns a
numbered contact sheet plus structured `pairs`. Each pair contains its original artifact IDs,
score, reasons, and reusable `paste_params` (`base`, `piece`, and `fit_box`). No individual preview
composites are imported into the session.

Use `role="head"` for head swaps, `"subject"` for full subjects, or `"object"` for props. `side` places
a default box on the left, center, or right. For head swaps, a detected target face takes precedence
over the side; set `target_box` to choose an exact target. Explicit boxes are clamped separately to
each background and backgrounds they miss are skipped.

Ranking measures aspect-ratio mismatch, enlargement, detail in the placement region, detected face
area for donor heads, and potential overlap with existing faces for subjects/props. It does not
identify people, determine facing direction, or judge expression or meaning. Inspect the contact
sheet before choosing a pair.

Previews use the existing hard-paste engine with nearest-neighbor scaling and hard alpha. They paste
the complete supplied donor. Use an existing cutout when possible; otherwise cut the subject first,
then replace the returned `piece` with that cutout artifact while reusing `fit_box`.
