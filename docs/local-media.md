# Local media and picture collections

In **Images & directions → Clips, pages & folders**, choose **Video / GIF**, **Pages / scans**, or **My folders**.
All source selection and folder operations are user-only. The art director cannot choose arbitrary
local paths or index folders itself.

## Frames and sequences

Pick a local GIF or video, set its starting time and optionally an ending time, then preview it.
The contact sheet shows up to eight sampled frames (the RPC supports up to twelve). GIF frames carry
actual frame-start times. Video frames carry requested seek positions, which can fall between encoded
frame timestamps. Selected pixels are frozen in a local preview cache; importing does not re-seek a
changed file.

Select one frame or several. Import individual frames or enable **Make an animated sequence** and set
the frame delay. Sequence order follows your selections. Animation uses the existing `animate` tool,
so its delay and input frames remain editable in the timeline.

Video decoding requires `ffmpeg` and `ffprobe` on the desktop core's PATH. GIFs use the bundled Pillow
library. Missing commands produce an actionable error; badshop does not install system packages.
Only local container formats are accepted by the decoder; playlists and network inputs are excluded.
The default video preview covers at most thirty seconds. A requested range can cover at most two
minutes. Source files are capped at 200 MB, with bounded subprocess time and image dimensions.

## Pages and regions

Pick a PDF, ordinary image, or supported multipage scan. Choose the page number, preview it, then
select the page. Drag on the large preview to mark a region or enter its four coordinates. Coordinate
labels refer to the rendered working image, at most 1000 pixels across, not the PDF's physical points.
Choose **Use whole frame / page** to reset the selection.

PDF rendering requires `pdftoppm` (Poppler) on PATH. The chosen PDF is rendered locally; it is not sent
to a provider. A cropped import keeps the page/frame image and executes a normal `cutout` step with
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
