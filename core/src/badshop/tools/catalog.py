"""Every tool, registered once, with the description an LLM sees."""

from badshop.engine import annotate, basic, compose, cutout, faces, filters, finish, garnish, sources, text
from badshop.engine.result import EngineResult
from badshop.tools.registry import ToolSpec, register

register(ToolSpec(
    name="fetch", params=sources.FetchParams, category="sources", network=True,
    run=lambda p, s: sources.fetch(p),
    summary="search Commons + Openverse, download an image or page URL, or grab the clipboard",
    description=("Get images. Search words are a keyword search: use a short literal description of the "
                 "picture ('labrador retriever sitting', not 'dog for meme'). Returns numbered candidates and "
                 "a contact sheet: look at the sheet and pick the one with the part you need at a usable "
                 "angle. query may also be an image URL or a web page URL (its preview image is used). "
                 "clipboard=true takes what the user copied. For a named person or thing prefer wiki."),
))

register(ToolSpec(
    name="wiki", params=sources.WikiParams, category="sources", network=True,
    run=lambda p, s: sources.wiki(p),
    summary="lead images of Wikipedia articles matching a name",
    description=("The lead image of the best-matching Wikipedia articles. The best first try for any named "
                 "person, place, building, animal breed or artwork; candidate 1 is almost always the exact "
                 "article."),
))

register(ToolSpec(
    name="emoji", params=sources.EmojiParams, category="sources", network=True,
    run=lambda p, s: sources.emoji(p),
    summary="transparent Twemoji PNGs by character, hex code or name",
    description=("Transparent 72px emoji images (Twemoji). Give characters (😂), hex codes (1f480) or names "
                 "(joy, rofl, sob, skull, fire, 100, eyes, ok, b, clown, moyai, flag_us, stonks...). Always "
                 "use this for emoji, never a search. Paste with repeat for emoji rain."),
))

register(ToolSpec(
    name="template", params=sources.TemplateParams, category="sources", network=True,
    run=lambda p, s: sources.template(p),
    summary="classic meme templates from Imgflip by name",
    description=("Classic meme templates by name from Imgflip's top 100 (drake, distracted boyfriend, two "
                 "buttons, change my mind...). Returns the best matches; list_all=true lists them all."),
))

register(ToolSpec(
    name="info", params=basic.InfoParams, category="inspect", mutates=False, read_only=True,
    run=lambda p, s: basic.info(p, s.load(p.image)),
    summary="print an image's size",
    description="Report an image's width and height in pixels. Cheap; use it before choosing coordinates.",
))

register(ToolSpec(
    name="prep", params=basic.PrepParams, category="inspect",
    run=lambda p, s: basic.prep(p, s.load(p.image)),
    summary="make a small working copy plus a gridded copy",
    description=("Make a working copy no larger than `max` px on its longest side, plus a copy with labeled "
                 "pixel gridlines. Work only with the working copy afterwards so coordinates you read "
                 "match what the tools use."),
))

register(ToolSpec(
    name="view", params=basic.ViewParams, category="inspect", mutates=False, read_only=True,
    run=lambda p, s: basic.view(p, s.load(p.image)),
    summary="look at an image, optionally with a coordinate grid",
    description=("Return an image so you can see it. Set grid=true to overlay labeled pixel gridlines "
                 "(every 50 px, labels every 100) when you need to read coordinates. Views larger than "
                 "`max` are scaled down and say so: grid labels are still source pixels, so use them as "
                 "they are; multiply anything else you measure on the view back up."),
))

register(ToolSpec(
    name="find", params=faces.FindParams, category="inspect", mutates=False, read_only=True,
    run=lambda p, s: faces.find(p, s.load(p.image)),
    summary="locate faces: head, face-oval, eyes, nose, mouth, chin and tilt",
    description=("Find faces and get exact coordinates instead of guessing: the head box (hair to neck; use "
                 "it to cut a head and as paste's fit_box on the target), the oval box (brows to chin; for "
                 "cutout oval=true), both eye points (for eyes, warp, censor), nose, mouth corners, chin, and "
                 "roll (tilt in degrees; paste rotate = piece roll - target roll to match). Faces are numbered "
                 "left to right. Returns an annotated image; check it when there is more than one face. "
                 "what=cats for cat faces. Finds nothing on cartoons and side views: use view with grid then."),
))

register(ToolSpec(
    name="text", params=text.TextParams, category="text",
    run=lambda p, s: text.caption(p, s.load(p.image)),
    summary="Impact caption, MS Paint text, or WordArt",
    description=("Write a caption. Default: Impact meme style, white with black outline, uppercase, "
                 "auto-sized, at the top; bottom=true for the punchline. style=paint is colored text with a "
                 "hard shadow (looks drawn in MS Paint); style=wordart is a rainbow face with a 3D "
                 "extrusion. at=[x,y] centers the text anywhere. A new line (or a typed \\n) forces a line break."),
))

register(ToolSpec(
    name="cutout", params=cutout.CutoutParams, category="cut",
    run=lambda p, s: cutout.cutout(p, s.load(p.image)),
    summary="crop a box and remove its background with hard edges",
    description=("Cut a piece out of an image. box is X1 Y1 X2 Y2; for a head use find's head box, generous "
                 "and cut across the neck. The background remover keeps the subject with a hard, jagged edge "
                 "on purpose. model=u2net_human_seg for people, isnet-anime for cartoons. oval=true cuts a "
                 "hard ellipse instead (face-only swap: use find's oval box). no_ai=true keeps the plain "
                 "rectangle. sticker=N adds a flat outline. If `opaque` is tiny, the box missed the subject."),
))

register(ToolSpec(
    name="paste", params=compose.PasteParams, category="compose",
    run=lambda p, s: compose.paste(p, s.load(p.base), s.load(p.piece)),
    summary="paste a cutout onto a base image",
    description=("Paste a cutout with nearest-neighbor scaling and no blending (the point of a bad "
                 "photoshop). Easiest: fit_box = the target's head box from find, scale 1.1. Or at + width "
                 "with an anchor (center for 'over the old head', bottom for 'standing on the ground'). "
                 "height squashes, rotate tilts (counter-clockwise), flip mirrors. repeat=N scatters N random "
                 "copies inside region (emoji rain, crowds). Each paste starts from the base you give it, so "
                 "to fix a placement re-run from the same base."),
))

register(ToolSpec(
    name="draw", params=annotate.DrawParams, category="effects",
    run=lambda p, s: annotate.draw(p, s.load(p.image)),
    summary="MS Paint annotations: circles, arrows, lines, rectangles",
    description=("Hand-drawn-looking annotations in the MS Paint tradition: circle=[x,y,r], arrow and line "
                 "=[x1,y1,x2,y2] (arrowhead at the end), rect=[x1,y1,x2,y2]; each is a list, so give as many "
                 "as you like. Red by default: 'circled in red' is the joke format."),
))

register(ToolSpec(
    name="censor", params=annotate.CensorParams, category="effects",
    run=lambda p, s: annotate.censor(p, s.load(p.image)),
    summary="pixelate, black-bar or blur rectangles",
    description=("Censor rectangles: style pixelate (default), bar (solid black, the classic eye bar: use a "
                 "box around find's eye points), or blur. block sets pixel size or blur radius."),
))

register(ToolSpec(
    name="eyes", params=annotate.EyesParams, category="effects",
    run=lambda p, s: annotate.eyes(p, s.load(p.image)),
    summary="laser eyes",
    description=("Laser beams with glow from each point in `at` (use find's eye points on the current "
                 "image: run find again after pasting a new head). angle is the beam direction in degrees "
                 "(0 = right, 90 = up, default 155 = up-left)."),
))

register(ToolSpec(
    name="filter", params=filters.FilterParams, category="effects",
    run=lambda p, s: filters.apply_filters(p, s.load(p.image)),
    summary="emboss, edges, solarize, posterize, sepia and other filters, in order",
    description=("The 'found the Filters menu' look: apply named filters in order (emboss, edges, contour, "
                 "solarize, posterize, invert, grayscale, sepia, blur, sharpen, oilpaint)."),
))

register(ToolSpec(
    name="warp", params=filters.WarpParams, category="effects",
    run=lambda p, s: filters.warp(p, s.load(p.image)),
    summary="bulge or pinch circular spots (giant eyes, huge nose)",
    description=("Bulge (strength > 0) or pinch (strength < 0) circles with blocky pixels. Giant eyes: a spot "
                 "on each find eye point with radius about 0.4x the eye distance. Huge nose: the nose point. "
                 "Default strength 0.6; 1.0 is enormous."),
))

register(ToolSpec(
    name="flare", params=garnish.FlareParams, category="effects",
    run=lambda p, s: garnish.flare(p, s.load(p.image)),
    summary="2004 lens flare",
    description=("A cheesy lens flare: glow, streak, and coloured ghost rings marching through the image center. "
                 "Use it for the 2004 'epic' look: put at on the sun, a lamp, a headlight or a glinting eye; "
                 "one per picture is plenty."),
))

register(ToolSpec(
    name="sparkle", params=garnish.SparkleParams, category="effects",
    run=lambda p, s: garnish.sparkle(p, s.load(p.image)),
    summary="clip-art four-point sparkles",
    description=("Clip-art sparkles with a soft glow, at given points and/or scattered at random (repeat, region). "
                 "Use it when something should look shiny, magical or fabulous: bling on jewellery, teeth or a "
                 "new car, a glow-up, a dream come true."),
))

register(ToolSpec(
    name="watermark", params=garnish.WatermarkParams, category="effects",
    run=lambda p, s: garnish.watermark(p, s.load(p.image)),
    summary="fake HyperCam, Bandicam, iFunny or Mematic watermarks",
    description=("Period-accurate fake watermarks, any combination: hypercam ('Unregistered HyperCam 2', "
                 "top-left), bandicam (top center), ifunny (adds a dark bar under the picture), mematic "
                 "(bottom center). text adds your own in a corner. Use it near the end to fake where the meme "
                 "came from: hypercam or bandicam for 'recorded on a 2005 PC', ifunny or mematic for 'reposted "
                 "from a meme app'."),
))

register(ToolSpec(
    name="save", params=finish.SaveParams, category="finish",
    run=lambda p, s: finish.save(p, s.load(p.image)),
    summary="write a crunchy low-quality JPEG, or a dithered GIF",
    description=("Finish as a low-quality JPEG (quality, passes to recompress, lowres for potato quality) or a "
                 "dithered GIF. Saved to the user's output folder; give a descriptive name."),
))

register(ToolSpec(
    name="deepfry", params=finish.DeepfryParams, category="finish",
    run=lambda p, s: finish.deepfry_tool(p, s.load(p.image)),
    summary="deep-fried meme treatment, written as a JPEG",
    description=("Deep-fry: red/yellow cast, blown-out saturation and contrast, oversharpened halos, grain, "
                 "rounds of low-quality JPEG. level 1-5 from how strongly the user put it (fried=3, "
                 "nuked=5). Replaces save. Give a descriptive name."),
))

register(ToolSpec(
    name="animate", params=finish.AnimateParams, category="finish",
    run=lambda p, s: finish.animate(p, [s.load(r) for r in p.images]),
    summary="animated GIF: flip between images, shake, flash, zoom, spin",
    description=("Make an animated GIF. Several images alternate (e.g. with and without lasers for flashing "
                 "laser eyes). effect shake/flash/zoom/spin; zoom with at=[x,y] and fry=5 is the classic "
                 "zoom-and-deep-fry. Give a descriptive name."),
))

register(ToolSpec(
    name="export", params=basic.ExportParams, category="finish", mutates=False,
    run=lambda p, s: EngineResult(lines=[f"exported: {s.export(p.image, p.name)}"]),
    summary="copy a finished image into the output folder",
    description=("Copy a finished image, unchanged (animation included), into the user's output folder "
                 "under a descriptive name, never overwriting. save and deepfry already do this; use export "
                 "for anything else the user wants to keep."),
))
