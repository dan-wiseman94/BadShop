# Local media and picture collections

**Add images → Add material** accepts pictures, HEIC phone photos, GIFs, clips,
PDFs and multipage scans from the same file picker. Drop files into the workspace
for the same routing. Pictures import immediately; clips and pages queue for
selection with the existing frame/page controls. **Done / next file** advances the
queue. **Cancel remaining imports** keeps completed imports. File batches offer
**Stop after current file**. Browser uploads are limited to 47 MiB per file;
the native file picker supports media up to 200 MB.

The same Add material panel offers clipboard images and direct image links.
Links use normal acquisition and network preferences; entering a link does not
download it until **Import link** is pressed.

## Screen regions and annotations

Choose **Capture screen region** in Add material. The native window hides while
capturing and returns afterward. On Wayland the desktop screenshot portal requests
permission and offers its capture choices. On Windows, macOS and X11, BadShop uses
the OS capture API; macOS may require Screen Recording permission.

Drag a region in the preview, or enter its crop coordinates, then import it.
The preview alone does not add project artifacts. Cancelling discards its cached
pixels. Only the chosen screen region enters the project; pixels outside that
region are not retained as an original. After **Done / next file**,
use **Manual tools → Text**, **Arrows & shapes**, or **Censor** to annotate. These
are recorded tools with ordinary undo/redo, replay and project persistence.
No screen is captured automatically or sent to a model by the capture action.
Capture is limited to 32 megapixels; working previews fit within 1000 pixels.

In **Images & directions → Clips, pages & folders**, choose **Video / GIF**, **Pages / scans**, or **My folders**.
All source selection and folder operations are user-only. The art director cannot choose arbitrary
local paths or index folders itself.

## Phone pictures

Import HEIC/HEIF files with the ordinary image picker or drop them into BadShop.
The bundled decoder creates a working PNG while retaining the original file bytes
in the project. Previews render a browser-compatible PNG, so displaying a phone
picture does not depend on the webview's HEIC support. Edits use the same recorded
tools as other pictures; saving and reopening preserves both copies. Malformed
files are refused without replacing existing project images.

## Frames and sequences

For an imported GIF, open **Manual tools → Edit GIF frames**. It selects the animated
original automatically. The frame strip supports trim, move, duplicate, delete,
reverse, ping-pong and a one-second hold. A blank duration keeps the source timing;
speed 2 doubles playback speed. Crop applies to all frames. Caption ranges refer
to output positions (zero-based start, exclusive end), with portable Latin-1 bitmap
text, exact line breaks, color and position. Overlong captions are refused.

**Preview changes** renders the animation without adding project data; **Cancel
changes** restores the initial settings. Apply records one undoable timeline step.
Frames, timing, captions and crop replay after reopening. Use GIF export to keep
animation. Limits are 200 input/output frames, 20 million decoded/output pixels,
and 655 seconds of output. Timings round to GIF's 10 ms units; adjacent identical
frames may encode as one equivalent hold. The source remains unchanged.

Pick a local GIF or video, set its starting time and optionally an ending time, then preview it.
The contact sheet shows up to eight sampled frames (the RPC supports up to twelve). GIF frames carry
actual frame-start times. Video frames carry requested seek positions, which can fall between encoded
frame timestamps. Selected pixels are frozen in a local preview cache; importing does not re-seek a
changed file.

Select one frame or several. Import individual frames or enable **Make an animated sequence** and set
the frame delay. Sequence order follows your selections. Animation uses the existing `animate` tool,
so its delay and input frames remain editable in the timeline.

Video decoding uses bundled FFmpeg libraries through PyAV in the isolated media worker.
GIFs use bundled Pillow. No separate video app or system decoder installation is needed.
Only local container formats are accepted by the decoder; playlists and network inputs are excluded.
The default video preview covers at most thirty seconds. A requested range can cover at most two
minutes. Source files are capped at 200 MB, with bounded worker time, memory and image dimensions.

## Pages and regions

Pick a PDF, ordinary image, or supported multipage scan. Choose the page number, preview it, then
select the page. Drag on the large preview to mark a region or enter its four coordinates. Coordinate
labels refer to the rendered working image, at most 1000 pixels across, not the PDF's physical points.
Choose **Use whole frame / page** to reset the selection.

PDF rendering uses bundled PDFium in the isolated media worker; no separate PDF app
is needed. The chosen PDF is rendered locally; it is not sent to a provider.
Encrypted or malformed PDFs and page numbers beyond the document are refused.
A cropped import keeps the page/frame image and executes a normal `cutout` step with
background removal disabled. Its crop box remains editable. The source filename, source hash, page
or time position, and crop coordinates persist in project metadata messages. Absolute local paths do
not enter the agent conversation. The original video/PDF is not embedded in the project; the selected
rendered frame/page pixels are sufficient for replay.

Preview caches retain at most sixteen recent sources. Expired previews can be recreated from their
source file. Already imported project images do not depend on the preview cache.

## Explicitly selected folders

Choose a specific folder and index it. badshop stores a local index of names, thumbnails, content
hashes, user tags, and descriptions. It skips hidden files, hidden directories, symlink files, and
symlink directories. The index is bounded by file count, directory count, time, and total decoded
source bytes. Warnings tell you when to choose a smaller folder.

Search matches words in filenames, tags, and descriptions. Identical file bytes are labeled as
duplicates. Search does not infer semantic descriptions automatically. **Ask agent for tags** imports
only the selected image and sends an explicit description request to the selected provider; provider
charges may apply. Review the reply in chat and save your chosen tags/description using **Edit
description / tags**. No whole folder or index is sent to the provider.

Reindexing preserves annotations only while the file's bytes match. Import refuses files that changed
since indexing or became links. Removing an index through `collections.remove` leaves the source
folder untouched. Collection indexes persist in the application data directory independently of
projects. Images you select are copied into the project with their descriptions and source hashes.
