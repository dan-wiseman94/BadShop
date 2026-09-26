---
name: badshop
description: Make deliberately bad, old-internet-style cut-and-paste photoshops by literally cropping pixels out of one photo and pasting them onto another with hard edges and no blending (a head on someone else's body, a face-swap-app oval, a cat dropped into a painting, a friend inserted into a stock photo, a meme template), plus the whole 2005-forum toolbox of Impact meme captions, rainbow WordArt, MS Paint text and red-circle annotations, pixelated censor bars, laser eyes, bulging eyes, lens flares, sparkles, fake HyperCam/Bandicam/iFunny watermarks, cloned crowds and emoji rain, emboss and solarize filters, potato-quality and animated GIFs, and deep-frying images into blown-out, grainy, JPEG-crushed memes. Use whenever the user asks for a "bad photoshop", a janky/crappy/2005-forum edit, a head or face swap, to "put X on Y", to paste something from one image into another and wants it to look obviously fake, to caption or meme-ify a picture or a meme template, to make a meme GIF, or to deep-fry, nuke, or crunch an image. Never generate the composite with an image model; run the bundled script instead.
allowed-tools: Bash(uv run -q ${CLAUDE_SKILL_DIR}/scripts/badshop.py *), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/badshop.py *)
---

# badshop

Image models re-render the whole picture and try to make edits seamless. A bad photoshop is bad *because* the pasted pixels are untouched: jagged magic-wand edges, wrong scale, mismatched lighting, JPEG crunch. So you are the art director, not the artist: you look at the images, pick coordinates, run the script, look at the result, adjust. The script owns the pixels.

## The script

```
uv run -q ${CLAUDE_SKILL_DIR}/scripts/badshop.py <command> ...
```

The script declares its own dependencies (PEP 723 header), so `uv run` builds and caches an environment on first use; don't pip-install anything. Every command prints `key: path` lines; use the paths it prints rather than guessing them. Run any command with `-h` for the full option list. Work files go to `badshop_work/` (relative to the cwd), and the editing commands all write `result.png` unless you pass `-o`, so give each step its own `-o` name when chaining. Finished output from `save`, `deepfry` and `animate` goes to `~/Pictures/badshop/` (override with `$BADSHOP_OUT` or `-o`), never overwriting an older file; pass `--name something_descriptive` so it isn't named after a work file.

### Getting images

| Command | What it does |
| --- | --- |
| `wiki "Name"` | Lead images of the best-matching Wikipedia articles (`-n`, default 4; #1 is almost always the exact article). The best first try for any named person, place, building, animal breed or artwork. |
| `fetch "words"` | Searches Wikimedia Commons and Openverse (Flickr, museums, etc.) interleaved, downloads `-n` (default 6) into `badshop_work/fetch/`, and writes a numbered `_sheet.png` contact sheet. `--source commons\|openverse` for one only. Each line notes the source and license. |
| `fetch URL` | A direct image link, or any web page: it follows the page's `og:image` preview (works for Commons file pages, news articles, most social posts). Transparency is kept. |
| `fetch --clipboard` | Saves the image the user copied (or follows a copied image/page link). Wayland `wl-paste`, X11 `xclip`, macOS `pngpaste`. |
| `emoji 😂 skull 1f480 ...` | Transparent 72px Twemoji PNGs by character, hex code, or name (`joy rofl sob skull fire 100 eyes ok b clown moyai flag_us stonks`...; run with a bad name to list them all). `--size` upscales with hard pixels. |
| `template "name"` | Classic meme templates from Imgflip's top 100 (drake, distracted boyfriend, two buttons, change my mind...), best `-n` matches with a sheet; `--list` prints them all. |

### Editing

| Command | What it does |
| --- | --- |
| `prep IMAGE` | Writes a ≤1000px working copy and a `_grid.png` copy with labeled pixel gridlines. Prints both paths and the size. |
| `find IMAGE` | Finds faces with YuNet (a small CNN) and prints, per face: the face box, a `head` box from hair to neck, an `oval` box from brows to chin, both eye points, nose, mouth corners, chin, and `roll` (tilt in degrees). Writes an annotated `_faces.png`. `--what cats` uses the older Haar detector (cat faces), `--min-score` trades misses for junk. |
| `cutout IMAGE [--box X1 Y1 X2 Y2]` | Crops that rectangle (or the whole image), removes its background (rembg), hard-thresholds the edge, trims to the subject. `--oval` instead cuts a hard ellipse filling the box (the face-swap-app look; feed it `find`'s `oval` box). `--sticker N` adds an N px flat outline (`--sticker-color`). `--grow N` for a halo of old background, `--no-ai` for the plain rectangle, `--model u2net_human_seg` for people, `isnet-anime` for cartoons. |
| `paste BASE PIECE` | Pastes with nearest-neighbor scaling and no blending. Placement is either `--fit-box X1 Y1 X2 Y2` (scale to cover that box and center on it; `--scale 1.1` to oversize) or `--at X Y --width W` with `--anchor topleft\|center\|bottom`. `--height H` squashes or stretches, `--rotate DEG` (counter-clockwise), `--flip`. `--repeat N` scatters N random copies (sizes 0.5–1.5× `--width`, random flips and tilts) inside `--region`, `--seed` to reshuffle. |
| `text IMAGE "words"` | Impact caption: white, black outline, uppercase, auto-sized, top by default or `--bottom`. `--style wordart` is a rainbow face with a 3D extrusion (`--color` sets the extrusion). `--style paint` is colored text with a hard black drop shadow (`--color`). `--rotate`, `--at X Y` to center it anywhere, `\n` forces a line break. Uses real Impact if installed, else downloads the free lookalike Anton once. |
| `draw IMAGE` | MS Paint annotations: `--circle X Y R`, `--arrow X1 Y1 X2 Y2`, `--line`, `--rect`, each repeatable; `--color red --width 6` defaults. |
| `censor IMAGE --box X1 Y1 X2 Y2` | `--style pixelate` (default), `bar` (black), or `blur`. `--box` is repeatable; `--block` sets the pixel size or blur radius. |
| `eyes IMAGE --at X Y --at X Y` | Laser eyes with glow. `--angle` sets the beam direction (0 = right, 90 = up; default 155, up-left), `--size`, `--color`. Feed it the eye points from `find`. |
| `warp IMAGE --at X Y R` | Bulges (or with negative `--strength`, pinches) a circle with blocky nearest-neighbor pixels. Repeatable. Giant eyes: `--at` each eye point with R ≈ 0.4× the eye distance. Huge nose: the nose point. `--strength` default 0.6, 1.0 is enormous. |
| `flare IMAGE --at X Y` | A 2004 lens flare: glow, streak, and colored ghost rings marching through the frame center. `--size`. |
| `sparkle IMAGE` | Clip-art four-point sparkles with a glow: `--at X Y` (repeatable) and/or `--repeat N --region ...`; `--size`, `--color`. |
| `watermark IMAGE hypercam bandicam ifunny mematic` | Fake screen-recorder/meme-app marks, any combination. `ifunny` adds a bar under the picture. `--text "..." --corner br` for your own. |
| `filter IMAGE NAME...` | `emboss`, `edges`, `contour`, `solarize`, `posterize`, `invert`, `grayscale`, `sepia`, `blur`, `sharpen`, `oilpaint`, applied in order. |
| `info IMAGE` | Prints the size. |

### Finishing

| Command | What it does |
| --- | --- |
| `save IMAGE` | JPEG at quality 35 (`--quality`, `--passes N` to recompress N times). `--lowres 0.3` for potato quality; `--gif` for a dithered 64-color GeoCities GIF (`--colors`). |
| `deepfry IMAGE` | Deep-fried meme treatment: red/yellow cast, blown-out saturation and contrast, oversharpened halos, grain, rounds of low-quality JPEG. `--level 1-5` (default 3), `--no-tint`. Replaces `save`. |
| `animate IMAGE [IMAGE...]` | Animated GIF. Several images alternate (e.g. with and without lasers for flashing laser eyes). `--effect shake\|flash\|zoom\|spin` (`--amount` = shake px or final zoom factor, `--at X Y` zoom target), `--fry N` deep-fries every frame (zoom ramps up to N as it closes in: the classic zoom-and-enhance fry), `--delay` ms. |

### Recipes

Every editing and finishing command is logged to `badshop_work/history.jsonl`. `recipe` turns the log into `badshop_work/recipe.json`: one clean step per output file (re-runs that rewrote the same `-o` replace the earlier attempt in place), so all the correction attempts collapse into the final pipeline. `run recipe.json` replays it; `--from N` restarts at a step. To make a knob, edit the recipe: put `{caption}` (any name) in an argument and replay with `--set "caption=NEW WORDS"`. Run `recipe --clear` before starting a new meme so old steps don't leak in.

## Workflow

0. Get the images. If the user gave files or paths, use those; if they say they copied one, `fetch --clipboard`; if they pasted a link (image or page), `fetch URL`. If they named a specific person, place, or thing ("Lincoln", "the Eiffel Tower", "the Mona Lisa"), start with `wiki "Name" -n 2`. For a generic subject ("a golden retriever", "a sad businessman") use `fetch` with a short literal description (it's a keyword search: "labrador retriever sitting" beats "dog for meme"). For a named meme format, `template`. For emoji, always `emoji`, never a search. Read the `_sheet.png` and pick the candidate with the part you need at a usable angle and size; the panel number is the file's suffix. If nothing usable turns up after one or two tries, ask the user for a file rather than guessing.
1. `recipe --clear`, then run `prep` on every input image and work only with the `_work.png` copies from then on. Read on a large image gets downscaled, which silently shifts the coordinates you read off it; the working copy is small enough that what you see is what the script gets. Skip `prep` for emoji and other small transparent stickers.
2. Find the part. For anything with a face, run `find` on the working copy first: it hands you the head box for the cut, the head box on the target for the paste, the oval box for face-only swaps, eye points for `eyes`, `warp` and `censor`, and roll for matching tilt, with no coordinate guessing. Glance at the `_faces.png` if there's more than one face so you cut the right one. If it finds nothing (cartoons, side views, statues), Read the `_grid.png` and pick the box yourself: be generous, since rembg keeps the subject and drops the rest, and for a head include the hair and cut across the neck or collar so the seam lands where a real bad photoshop's would.
3. Cut. Whole head: `cutout --box <head box>` (add `--model u2net_human_seg` for people). Face only: `cutout --oval --box <oval box>`. If the kept percentage is tiny or nothing is kept, widen the box, try another `--model`, or use `--no-ai` and paste the plain rectangle (also period-accurate). `--sticker 8` for the modern shitpost look.
4. Place it. With `find` boxes on the target, `paste --fit-box <target head box> --scale 1.1` (or `<target oval box> --scale 1.05` for an oval) does the whole placement; to match tilt add `--rotate <piece roll - target roll>`, or deliberately don't. Otherwise Read the target's `_grid.png` and choose `--at` with an anchor that matches how you're thinking about it (`center` for "over the old head", `bottom` for "standing on the ground") and a `--width`. Decide the scale on purpose: roughly right for a plausible-bad look, clearly wrong if the user asked for worse.
5. Read the result. Fix placement or scale at most once or twice, re-running `paste` against the same base with the same `-o` (each paste starts from the base you give it, so corrections don't stack, and the recipe keeps only the last). Then stop. It is supposed to look bad; don't polish it.
6. Add extras the user asked for, each as its own step with its own `-o`: `text` for captions, `draw` to circle or point at the joke, `censor` for eye bars, `eyes` for lasers (run `find` on the composite for the new eye points), `warp` for giant eyes, `flare`/`sparkle`/`watermark` for garnish, `paste --repeat` with an `emoji` for emoji rain, `filter` for the found-the-Filters-menu look.
7. Finish with `save`, `deepfry` (if they asked for deep-fried, nuked, cooked, crunched; pick the level from how strongly they put it), or `animate` (if they want it moving), always with `--name`. Tell the user the path it printed. If they'll want variations ("now do it with a different caption"), run `recipe`, template the knob, and `run --set`.

For several pieces, chain pastes: the result of one is the base of the next. If the user only wants an existing image captioned, deep-fried, or filtered, run `prep` and then just that command on the working copy; there's no cutting to do.

## Style rules

- Never feather, blend, color-match, add shadows, or clean up edges, and never route the image through an image-generation model to "fix" it. Bad is the deliverable.
- Knobs for making it worse when asked: `--grow 6` for a halo of the old background, `--rotate` a few degrees off, `--height` to squash, `--width` too big or too small, `--repeat 40` for a crowd of the same head, `warp --strength 1`, `save --quality 15 --passes 3`, `save --lowres 0.25`, `deepfry --level 5`, `animate --effect zoom --fry 5`.
- Captions default to Impact at the top; put a punchline at the `--bottom`. Use `--style wordart` for the 2003 Word-document look, `--style paint` when it should look drawn in MS Paint, and `draw` in red for anything that should look circled by hand.
- If the user's request is vague ("put my dog in this"), make the obvious call and show them; a wrong guess costs one re-run.

## Setup

Needs `uv` (the script's header installs Pillow, NumPy, OpenCV 4.x and rembg into a cached environment). Without uv: `pip install pillow numpy "opencv-python-headless<5" "rembg[cpu]"` and run with `python3`; OpenCV must stay below 5, which removed the Haar cascades used for cat faces. Downloads happen once, on first use: the rembg model (~170 MB per `--model`, into `~/.local/share/rembg/`), the YuNet face model (230 KB) and the Anton/Comic Neue fonts (into `~/.cache/badshop/`). `fetch`, `wiki`, `emoji` and `template` need internet access. `fetch --clipboard` needs `wl-clipboard` (Wayland), `xclip` (X11) or `pngpaste` (macOS).
