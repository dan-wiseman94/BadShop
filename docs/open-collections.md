# Collections that work without API keys

In **Images & directions → Find images**, choose **Cleveland Museum of Art** or **Wellcome Collection**
in the collection selector. Both also participate in **All public collections** without configuration.
The same sources are available as `discover(source="cleveland")` and `discover(source="wellcome")`.

## Cleveland Museum of Art

Try concrete subjects such as `armor`, `cat`, `woodcut`, or an artist's name. The collection supplies
paintings, prints, sculpture, clothing, and decorative objects. Discovery requests works with images
and a CC0 designation, then checks each returned artwork's image rights again. CC0 metadata alone
does not qualify a copyrighted image.

Previews use the museum's web JPEG. **Use image** downloads its larger print JPEG when available,
falling back to the web JPEG when needed. The archival TIFF is not selected: it can be very large and
is unnecessary for the app's working copies. Title, creator, collection page, and CC0 designation
travel with the selected image. The museum's [API documentation](https://openaccess-api.clevelandart.org/)
describes its image sizes and fields; its [Open Access page](https://www.clevelandart.org/open-access)
explains how CC0 images are identified.

## Wellcome Collection

Try `poster`, `microscope`, `botanical`, `dentist`, or a named historical subject. The image catalogue
includes photographs, prints, advertisements, illustrations, and scientific material. Discovery
requests CC0, Public Domain Mark, CC BY, and CC BY-SA images, and checks the license of the actual
image location before displaying it. An image's availability online is not treated as permission to
reuse it. Restricted locations and other licenses are skipped.

The thumbnail is a 320-pixel IIIF derivative. **Use image** requests the full image as a JPEG and keeps
the image page, creator/credit, and license link. This is a full image of the catalogued page or object,
not an automatic extraction of its subject. Crop it afterward when needed. See Wellcome's
[Catalogue API](https://developers.wellcomecollection.org/api/catalogue) and
[IIIF API](https://developers.wellcomecollection.org/api/iiif).

## Bounds and source status

Each adapter makes one search request for at most 24 metadata records; discovery does not crawl
result pages. Search replies use the existing 8-second timeout and 5 MiB metadata limit. Preview
downloads retain their 4 MiB and 4-megapixel limits. Full images use the existing acquisition limits;
a source image that exceeds them can be refused even when its preview worked. Network availability,
search ranking, and upstream collection contents can change. Imported images remain in the project
for reproducible replay.

The core's `discovery.source_status()` helper returns each concrete source's `id`, `name`,
`configured`, `requires_key`, and `env_var`. `configured` means that required environment
configuration is present, or that none is required. It does not test network access or validate an API
key. The custom image gateway requires its URL environment variable despite not requiring a key.
The helper returns environment variable names only; values, keys, and gateway addresses are omitted.
