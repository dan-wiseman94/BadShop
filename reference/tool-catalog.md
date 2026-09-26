# Tool catalog (generated from reference/badshop.py argparse definitions)

Every command below becomes one tool in the registry. Positional args first, then options.

## `prep` — make a small working copy plus a gridded copy

| arg | type / choices | default | help |
|---|---|---|---|
| `image` | str |  |  |
| `--max` | int | `1000` | longest side in px (default 1000) |
| `-o/--out` | str |  | path for the working copy (default badshop_work/<name>_work.png) |

## `fetch` — search Commons + Openverse, download an image/page URL, or grab the clipboard

| arg | type / choices | default | help |
|---|---|---|---|
| `query` | str ×? |  | search words like "mona lisa painting", or an image or web page URL |
| `--source` | all \| commons \| openverse | `all` | where to search (default all: Wikimedia Commons and Openverse, interleaved) |
| `-n` | 1-12 | `6` | how many candidates to download (default 6) |
| `--clipboard` | flag |  | save the image (or image link) on the clipboard |
| `-o/--out` | str |  | output path (URL and clipboard modes; searches go to badshop_work/fetch/) |

## `wiki` — lead images of Wikipedia articles matching a name

| arg | type / choices | default | help |
|---|---|---|---|
| `title` | str |  | a person, place or thing, e.g. "Abraham Lincoln" |
| `-n` | 1-8 | `4` | how many matching articles (default 4; the first is usually the exact one) |
| `--lang` | str | `en` | Wikipedia language code (default en) |

## `emoji` — transparent Twemoji PNGs by character, hex code, or name

| arg | type / choices | default | help |
|---|---|---|---|
| `emoji` | str ×+ |  | e.g. 😂 1f480 skull; names: 100, b, cap, clown, cold, crown, eagle, exploding, eyes, fire, flag_us, flex, goat, heart_eyes, hot, joy, laughing, money, moyai, nerd, ok, pleading, pray, rofl, salute, skull, sob, stonks, sunglasses, thinking |
| `--size` | int |  | nearest-neighbor upscale to this many px (default: the 72px original) |

## `template` — classic meme templates from Imgflip

| arg | type / choices | default | help |
|---|---|---|---|
| `name` | str ×? |  | e.g. "drake", "distracted boyfriend", "two buttons" |
| `-n` | 1-8 | `3` | how many best matches to download (default 3) |
| `--list` | flag |  | print all template names instead |

## `find` — locate faces and print head, oval, eye, nose, mouth, chin and tilt

| arg | type / choices | default | help |
|---|---|---|---|
| `image` | str |  |  |
| `--what` | faces \| cats \| all | `faces` | faces (default, human), cats, or all |
| `--detector` | auto \| yunet \| haar | `auto` | auto (default): YuNet with landmarks, falling back to Haar cascades |
| `--min-score` | float | `0.7` | YuNet confidence cutoff 0-1 (default 0.7; lower finds more, and more junk) |

## `cutout` — crop a box and remove its background with hard edges

| arg | type / choices | default | help |
|---|---|---|---|
| `image` | str |  |  |
| `--box` | int ×4 |  | rectangle to cut, pixel coords; omit to use the whole image |
| `--model` | str | `u2net` | rembg model: u2net (default, fast), birefnet-general (cleaner), u2net_human_seg, isnet-anime |
| `--threshold` | int | `128` | alpha cutoff 0-255 (default 128) |
| `--grow` | int |  | dilate the mask N px to drag in a halo of old background |
| `--no-ai` | flag |  | skip background removal; keep the whole rectangle |
| `--oval` | flag |  | cut a hard-edged ellipse filling the box instead (face-only swap; use `find`'s oval box) |
| `--sticker` | int |  | add an N px flat outline around the shape |
| `--sticker-color` | str | `white` | outline color for --sticker (default white) |
| `-o/--out` | str |  | default badshop_work/<name>_cutout.png |

## `paste` — paste a cutout onto a base image

| arg | type / choices | default | help |
|---|---|---|---|
| `base` | str |  |  |
| `piece` | str |  |  |
| `--at` | int ×2 |  | where the anchor goes, pixel coords |
| `--anchor` | topleft \| center \| bottom | `topleft` | which point of the piece --at refers to (default topleft; bottom = bottom-center) |
| `--width` | float |  | width to scale the piece to |
| `--height` | float |  | height; omit to keep the aspect ratio, set to squash or stretch |
| `--fit-box` | int ×4 |  | instead of --at/--width: scale and center the piece to cover this box |
| `--scale` | float | `1.0` | with --fit-box, oversize factor (1.3 = 30% too big) |
| `--rotate` | float |  | degrees counter-clockwise |
| `--flip` | flag |  | mirror the piece horizontally |
| `--repeat` | int |  | scatter this many random copies (size 0.5-1.5x --width) instead |
| `--region` | int ×4 |  | with --repeat, only scatter inside this box |
| `--seed` | int | `1` | with --repeat, change for a different scatter |
| `-o/--out` | str |  | default badshop_work/result.png |

## `text` — Impact caption, MS Paint text, or WordArt

| arg | type / choices | default | help |
|---|---|---|---|
| `image` | str |  |  |
| `text` | str |  | the words; use \n for a manual line break |
| `--style` | impact \| paint \| wordart | `impact` | impact: white, black outline, uppercase; paint: colored with a hard shadow; wordart: rainbow face with a 3D extrusion |
| `--bottom` | flag |  | bottom caption (default is top) |
| `--at` | int ×2 |  | center the text on this point instead |
| `--size` | int |  | font size in px (default: fits the image width) |
| `--color` | str |  | paint text color (default red), or wordart extrusion color (default purple) |
| `--rotate` | float |  | degrees counter-clockwise |
| `--margin` | int | `20` |  |
| `--font` | str |  | path or name of a font file to use instead |
| `-o/--out` | str |  | default badshop_work/result.png |

## `draw` — MS Paint annotations; repeat any shape option for more

| arg | type / choices | default | help |
|---|---|---|---|
| `image` | str |  |  |
| `--circle` | int ×3 (repeatable) |  |  |
| `--arrow` | int ×4 (repeatable) |  |  |
| `--line` | int ×4 (repeatable) |  |  |
| `--rect` | int ×4 (repeatable) |  |  |
| `--color` | str | `red` |  |
| `--width` | int | `6` | stroke width in px (default 6) |
| `-o/--out` | str |  | default badshop_work/result.png |

## `censor` — pixelate, black-bar or blur rectangles

| arg | type / choices | default | help |
|---|---|---|---|
| `image` | str |  |  |
| `--box` | int ×4 (repeatable) |  |  |
| `--style` | pixelate \| bar \| blur | `pixelate` |  |
| `--block` | int | `16` | pixel size for pixelate, blur radius for blur (default 16) |
| `-o/--out` | str |  | default badshop_work/result.png |

## `eyes` — laser eyes

| arg | type / choices | default | help |
|---|---|---|---|
| `image` | str |  |  |
| `--at` | int ×2 (repeatable) |  | an eye position; give it twice for two eyes |
| `--angle` | float | `155` | beam direction in degrees, 0 = right, 90 = up (default 155) |
| `--size` | int |  | beam thickness in px (default: scaled to the image) |
| `--color` | str | `red` |  |
| `-o/--out` | str |  | default badshop_work/result.png |

## `warp` — bulge or pinch circular spots (giant eyes, huge nose)

| arg | type / choices | default | help |
|---|---|---|---|
| `image` | str |  |  |
| `--at` | int ×3 (repeatable) |  | center and radius of a spot; repeatable |
| `--strength` | float | `0.6` | positive bulges, negative pinches (default 0.6; 1.0 is huge, -0.5 is a strong pinch) |
| `-o/--out` | str |  | default badshop_work/result.png |

## `flare` — lens flare

| arg | type / choices | default | help |
|---|---|---|---|
| `image` | str |  |  |
| `--at` | int ×2 |  | where the light is |
| `--size` | int |  | glow radius in px (default: a sixth of the short side) |
| `-o/--out` | str |  | default badshop_work/result.png |

## `sparkle` — clip-art four-point sparkles

| arg | type / choices | default | help |
|---|---|---|---|
| `image` | str |  |  |
| `--at` | int ×2 (repeatable) |  | a sparkle; repeatable |
| `--repeat` | int |  | scatter this many at random instead (or as well) |
| `--region` | int ×4 |  | with --repeat, only scatter inside this box |
| `--size` | int |  | sparkle radius in px (default: scaled to the image) |
| `--color` | str | `#fff27a` | glow color (default pale yellow) |
| `--seed` | int | `1` |  |
| `-o/--out` | str |  | default badshop_work/result.png |

## `watermark` — fake screen-recorder / meme-app watermarks

| arg | type / choices | default | help |
|---|---|---|---|
| `image` | str |  |  |
| `names` | hypercam \| bandicam \| ifunny \| mematic ×* |  | hypercam, bandicam, ifunny, mematic |
| `--text` | str |  | your own watermark text as well |
| `--corner` | tl \| tr \| bl \| br | `br` | corner for --text (default br) |
| `-o/--out` | str |  | default badshop_work/result.png |

## `filter` — apply one or more effects, in order

| arg | type / choices | default | help |
|---|---|---|---|
| `image` | str |  |  |
| `names` | blur \| contour \| edges \| emboss \| grayscale \| invert \| oilpaint \| posterize \| sepia \| sharpen \| solarize ×+ |  | blur, contour, edges, emboss, grayscale, invert, oilpaint, posterize, sepia, sharpen, solarize |
| `-o/--out` | str |  | default badshop_work/result.png |

## `save` — write a low-quality JPEG, or a dithered GIF

| arg | type / choices | default | help |
|---|---|---|---|
| `image` | str |  |  |
| `--quality` | int | `35` | JPEG quality 1-95 (default 35) |
| `--passes` | int | `1` | recompress this many times for more artifacts |
| `--lowres` | float |  | downscale to this fraction and back up, e.g. 0.3 for potato quality |
| `--gif` | flag |  | write a dithered 1999-style GIF instead of a JPEG |
| `--colors` | int | `64` | with --gif, palette size (default 64) |
| `--name` | str |  | file name without extension, saved in the output folder |
| `-o/--out` | str |  | default /home/dan/Pictures/badshop/<name>, never overwriting |

## `deepfry` — deep-fried meme treatment, written as a JPEG

| arg | type / choices | default | help |
|---|---|---|---|
| `image` | str |  |  |
| `--level` | 1-5 | `3` | 1 = lightly toasted, 3 = default, 5 = nuked |
| `--no-tint` | flag |  | skip the red/yellow color cast |
| `--name` | str |  | file name without extension, saved in the output folder |
| `-o/--out` | str |  | default /home/dan/Pictures/badshop/<name>, never overwriting |

## `animate` — animated GIF from one or more images

| arg | type / choices | default | help |
|---|---|---|---|
| `images` | str ×+ |  | frames cycle through these (e.g. with and without laser eyes) |
| `--effect` | none \| shake \| flash \| zoom \| spin | `none` |  |
| `--frames` | int |  | frame count (default depends on the effect) |
| `--delay` | int | `80` | ms per frame (default 80) |
| `--amount` | float |  | shake: max px offset; zoom: final zoom factor (default 3) |
| `--at` | int ×2 |  | zoom target (default: the center) |
| `--hold` | int | `6` | zoom: repeat the last frame this many times (default 6) |
| `--fry` | 1-5 |  | deep-fry every frame at this level (zoom ramps up to it) |
| `--colors` | int | `128` | palette size per frame (default 128) |
| `--seed` | int | `1` |  |
| `--name` | str |  | file name without extension, saved in the output folder |
| `-o/--out` | str |  | default /home/dan/Pictures/badshop/<name>, never overwriting |

## `recipe` — write the logged editing commands as a replayable recipe

| arg | type / choices | default | help |
|---|---|---|---|
| `--last` | int |  | only use the last N logged commands |
| `--clear` | flag |  | forget the history (do this before starting a new meme) |
| `-o/--out` | str |  | default badshop_work/recipe.json |

## `run` — replay a recipe

| arg | type / choices | default | help |
|---|---|---|---|
| `recipe` | str |  |  |
| `--set` | str (repeatable) |  | fill "{NAME}" in the recipe; repeatable |
| `--from` | int | `1` | start at this step number |

## `info` — print an image's size

| arg | type / choices | default | help |
|---|---|---|---|
| `image` | str |  |  |

