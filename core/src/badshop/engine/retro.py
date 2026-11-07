"""Additive pixel-era layouts and primitives. No generated imagery or downloaded fonts.

Definitions are versioned recipe data. All geometry, colors and random choices are explicit;
the original engine remains untouched. Text uses Pillow's bundled bitmap font.
"""

import random
from typing import Literal

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps, ImageSequence
from pydantic import Field, model_validator

from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import Color, ImageRef, Params, Seed

# id, name, era, family, size, background, foreground, accent, furniture
_ROWS = [
    (
        "ansi-bbs",
        "ANSI bulletin board",
        "1980s",
        "Text screens",
        640,
        400,
        "#000000",
        "#aaaaaa",
        "#00aaaa",
        "terminal",
    ),
    (
        "irc",
        "ASCII / IRC log",
        "1990s",
        "Text screens",
        640,
        400,
        "#f6f6f6",
        "#111111",
        "#0000aa",
        "terminal",
    ),
    (
        "hypercard",
        "One-bit HyperCard",
        "1980s",
        "Desktop",
        512,
        342,
        "#ffffff",
        "#000000",
        "#777777",
        "window",
    ),
    (
        "geocities",
        "GeoCities homepage",
        "1990s",
        "Personal web",
        640,
        480,
        "#000033",
        "#ffff00",
        "#00ffff",
        "web",
    ),
    (
        "badge",
        "88 x 31 web button",
        "1990s",
        "Tiny graphics",
        88,
        31,
        "#000080",
        "#ffffff",
        "#ffff00",
        "badge",
    ),
    ("blinkie", "Blinkie strip", "2000s", "Tiny graphics", 150, 20, "#ffb6dc", "#421240", "#ffffff", "badge"),
    ("portal", "Portal news page", "1990s", "Personal web", 640, 480, "#eeeeee", "#000066", "#ffcc00", "web"),
    ("y2k", "Y2K chrome portal", "2000s", "Personal web", 640, 480, "#bcc8e0", "#222255", "#00ffff", "web"),
    ("winamp", "Winamp player skin", "1990s", "Desktop", 550, 232, "#242529", "#77ff55", "#92969c", "player"),
    (
        "desktop",
        "Desktop error pile",
        "1990s",
        "Desktop",
        640,
        480,
        "#008080",
        "#000000",
        "#000080",
        "window",
    ),
    (
        "messenger",
        "AIM / MSN conversation",
        "2000s",
        "Social",
        480,
        480,
        "#e5e5e5",
        "#111111",
        "#3447a0",
        "chat",
    ),
    ("forum", "phpBB forum post", "2000s", "Social", 640, 420, "#dce5ee", "#172940", "#315f8a", "forum"),
    (
        "clan",
        "Clan signature banner",
        "2000s",
        "Tiny graphics",
        480,
        160,
        "#131924",
        "#dddddd",
        "#99dd00",
        "banner",
    ),
    ("myspace", "MySpace profile", "2000s", "Social", 640, 480, "#efe4f6", "#45135b", "#ff66bb", "web"),
    (
        "glitter",
        "Glitter scrapbook",
        "2000s",
        "Personal web",
        480,
        480,
        "#330033",
        "#ffddff",
        "#ff44dd",
        "scrapbook",
    ),
    (
        "livejournal",
        "LiveJournal / dollmaker",
        "2000s",
        "Social",
        640,
        480,
        "#e2d7e8",
        "#412e4d",
        "#b383c4",
        "web",
    ),
    (
        "sprite-comic",
        "Flash-era sprite comic",
        "2000s",
        "Comics",
        640,
        360,
        "#dddddd",
        "#111111",
        "#ffffff",
        "comic",
    ),
    ("lolcat", "LOLcat / advice animal", "2000s", "Memes", 480, 480, "#552277", "#ffffff", "#ffaa00", "meme"),
    (
        "demotivator",
        "Demotivational poster",
        "2000s",
        "Memes",
        640,
        480,
        "#000000",
        "#ffffff",
        "#ffffff",
        "poster",
    ),
    ("rage", "Rage comic", "2010s", "Comics", 640, 480, "#ffffff", "#000000", "#dd0000", "comic"),
    ("greentext", "Greentext post", "2000s", "Social", 640, 420, "#ffffee", "#117743", "#789922", "forum"),
    (
        "aero",
        "Frutiger Aero desktop",
        "2000s",
        "Desktop",
        640,
        480,
        "#1e95cf",
        "#ffffff",
        "#8ddd6e",
        "window",
    ),
    (
        "tutorial",
        "Paint tutorial screenshot",
        "2000s",
        "Desktop",
        640,
        480,
        "#c0c0c0",
        "#111111",
        "#000080",
        "window",
    ),
    ("repost", "Repost screenshot", "2010s", "Memes", 480, 540, "#fafafa", "#111111", "#888888", "poster"),
    (
        "vaporwave",
        "Tumblr / vaporwave collage",
        "2010s",
        "Personal web",
        640,
        480,
        "#6f4c91",
        "#ffb8f5",
        "#56e0e5",
        "scrapbook",
    ),
    (
        "webcore",
        "Webcore sticker shrine",
        "2020s",
        "Personal web",
        640,
        480,
        "#171323",
        "#e8d7ff",
        "#adff2f",
        "scrapbook",
    ),
    (
        "nokia",
        "Monochrome phone screen",
        "1990s",
        "Text screens",
        168,
        120,
        "#9bab71",
        "#273524",
        "#67794f",
        "terminal",
    ),
    (
        "teletext",
        "Teletext page",
        "1980s",
        "Text screens",
        480,
        400,
        "#000000",
        "#ffffff",
        "#ffff00",
        "terminal",
    ),
]
STYLES = {
    r[0]: dict(
        zip(
            (
                "id",
                "name",
                "era",
                "family",
                "width",
                "height",
                "background",
                "foreground",
                "accent",
                "furniture",
            ),
            r,
        ),
        version=1,
    )
    for r in _ROWS
}
PALETTES = {
    "mono": ["#000000", "#ffffff"],
    "gameboy": ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"],
    "cga": ["#000000", "#55ffff", "#ff55ff", "#ffffff"],
    "ega": [
        "#000000",
        "#0000aa",
        "#00aa00",
        "#00aaaa",
        "#aa0000",
        "#aa00aa",
        "#aa5500",
        "#aaaaaa",
        "#555555",
        "#5555ff",
        "#55ff55",
        "#55ffff",
        "#ff5555",
        "#ff55ff",
        "#ffff55",
        "#ffffff",
    ],
    "web": ["#000000", "#000080", "#008080", "#800080", "#c0c0c0", "#ffffff", "#ffff00", "#00ffff"],
}


def color(value):
    try:
        return ImageColor.getrgb(value)
    except ValueError:
        raise EngineError(f"unknown color: {value}") from None


def text(im, value, xy, fill, scale=1, max_width=None, exact=True):
    # Fixed 6x11 Latin-1 bitmap, stable across operating systems. Missing glyphs are an error.
    try:
        value.encode("latin-1")
    except UnicodeEncodeError:
        raise EngineError(
            "this bitmap font supports Latin-1 text", hint="use the existing text tool for other scripts"
        ) from None
    font = ImageFont.load_default_imagefont()
    lines = value.split("\n")
    limit = max(1, max_width // (6 * scale)) if max_width else 4096
    wrapped = []
    for line in lines:
        if exact and len(line) > limit:
            raise EngineError(
                "caption does not fit",
                hint=f"use at most {limit} characters per line, add a line break, or lower text scale",
            )
        wrapped.extend([line[i : i + limit] for i in range(0, len(line), limit)] or [""])
    mask = Image.new("1", (max(1, max(map(len, wrapped)) * 6), max(11, len(wrapped) * 11)))
    draw = ImageDraw.Draw(mask)
    for i, line in enumerate(wrapped):
        draw.text((0, i * 11), line, font=font, fill=1)
    mask = mask.resize((mask.width * scale, mask.height * scale), Image.Resampling.NEAREST)
    if exact and (xy[1] + mask.height > im.height or xy[0] + mask.width > im.width):
        raise EngineError("caption exceeds the canvas", hint="shorten the text or lower text scale")
    im.paste(color(fill), xy, mask)


def paste(im, source, box, fit="contain"):
    x, y, w, h = box
    source = source.convert("RGBA")
    if fit == "cover":
        source = ImageOps.fit(source, (w, h), method=Image.Resampling.NEAREST)
    elif fit == "stretch":
        source = source.resize((w, h), Image.Resampling.NEAREST)
    else:
        ratio = min(w / source.width, h / source.height)
        source = source.resize(
            (max(1, round(source.width * ratio)), max(1, round(source.height * ratio))),
            Image.Resampling.NEAREST,
        )
    alpha = source.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
    im.paste(source.convert("RGB"), (x + (w - source.width) // 2, y + (h - source.height) // 2), alpha)


def result(im, name, **data):
    return EngineResult(outputs=[Output("result", im, name + ".png")], data=data)


StyleId = Literal[tuple(STYLES)]


class RetroParams(Params):
    style: StyleId = 'geocities'
    images: list[ImageRef] = Field(default_factory=list, max_length=4)
    title: str = Field("WELCOME TO MY PAGE", max_length=240)
    caption: str = Field("", max_length=1000)
    seed: Seed = 1
    density: Literal["sparse", "balanced", "chaotic"] = "balanced"
    text_scale: int = Field(1, ge=1, le=4)
    exact_text: bool = True
    fit: Literal["contain", "cover", "stretch"] = "contain"


def render(p, images):
    if p.style not in STYLES:
        raise EngineError("unknown retro style", hint="choose a style from retro.list")
    s = STYLES[p.style]
    w, h = s["width"], s["height"]
    bg, fg, accent = s["background"], s["foreground"], s["accent"]
    im = Image.new("RGB", (w, h), color(bg))
    d = ImageDraw.Draw(im)
    rng = random.Random(p.seed)
    kind = s["furniture"]
    title_y = 8
    cap_y = h - 32
    title_x = 12
    slots = []
    if kind == "badge":
        d.rectangle((0, 0, w - 1, h - 1), outline=fg, width=1)
        d.line((1, h - 2, w - 2, h - 2, w - 2, 1), fill=accent, width=1)
        title_x = 3
        title_y = max(2, (h - 11) // 2)
        cap_y = h
        if images:
            slots = [(2, 2, h - 4, h - 4)]
            title_x = h
    elif kind == "terminal":
        d.rectangle((4, 4, w - 5, 20), fill=accent)
        title_y = 28
        cap_y = h - 28
        slots = [(12, 60, w - 24, h - 100)]
        if p.style == "teletext":
            for i, c in enumerate(["#ff0000", "#00ff00", "#ffff00", "#00ffff"]):
                d.rectangle((i * w // 4, h - 14, (i + 1) * w // 4 - 1, h - 1), fill=c)
    elif kind == "window":
        if p.style == "desktop":
            for i in range(3):
                x, y = 22 + i * 30, 26 + i * 28
                d.rectangle(
                    (x, y, w - 65 + i * 15, h - 100 + i * 20), fill="#c0c0c0", outline="#ffffff", width=2
                )
                d.rectangle((x + 3, y + 3, w - 68 + i * 15, y + 22), fill=accent)
        d.rectangle((8, 8, w - 9, h - 30), fill=bg, outline=fg, width=2)
        d.rectangle((11, 11, w - 12, 32), fill=accent)
        d.rectangle((w - 30, 14, w - 16, 28), fill="#c0c0c0", outline="#ffffff")
        text(im, "X", (w - 26, 16), "#000000")
        title_y = 15
        title_x = 16
        slots = [(24, 62, w - 48, h - 124)]
        cap_y = h - 54
        d.rectangle((0, h - 24, w, h), fill="#c0c0c0", outline="#ffffff")
        text(im, "START | BADSHOP", (8, h - 18), "#000000")
        if p.style == "tutorial":
            for i, c in enumerate(PALETTES["ega"]):
                d.rectangle((14 + i * 18, 38, 28 + i * 18, 51), fill=c, outline="#000000")
    elif kind in ("forum", "chat"):
        d.rectangle((8, 8, w - 9, 34), fill=accent)
        title_y = 14
        title_x = 16
        d.rectangle((10, 45, 108, h - 46), fill=accent)
        slots = [(18, 54, 82, 82), (120, 76, w - 138, h - 136)]
        cap_y = h - 30
        text(im, "online", (22, 145), fg)
        d.line((116, 45, 116, h - 46), fill=fg)
    elif kind == "web":
        if p.style == "geocities":
            for _ in range({"sparse": 12, "balanced": 45, "chaotic": 100}[p.density]):
                x, y = rng.randrange(w), rng.randrange(h)
                d.line((x - 2, y, x + 2, y), fill=accent)
                d.line((x, y - 2, x, y + 2), fill=accent)
        d.rectangle((8, 8, w - 9, 40), outline=accent, width=2)
        title_y = 17
        d.rectangle((8, 50, 112, h - 40), outline=accent, width=2)
        for i, label in enumerate(["HOME", "GUESTBOOK", "LINKS", "ABOUT ME", "WEBRING"]):
            text(im, label, (16, 65 + i * 28), fg)
        slots = [(126, 54, w - 140, h - 110)]
        d.rectangle((8, h - 32, 112, h - 10), fill=accent)
        text(im, "001337", (24, h - 27), bg)
        title_x = 16
        cap_y = h - 28
    elif kind == "player":
        d.rectangle((4, 4, w - 5, h - 5), outline=accent, width=4)
        slots = [(16, 42, 180, 140)]
        title_x = 18
        for i in range(20):
            x = 220 + i * 15
            bar = rng.randrange(10, 105)
            d.rectangle((x, 150 - bar, x + 8, 150), fill=fg)
        text(im, "[<<] [>] [||] [STOP] [>>]", (220, 174), fg)
        cap_y = h - 30
    elif kind == "comic":
        slots = [(8, 40, w // 2 - 12, h - 84), (w // 2 + 4, 40, w // 2 - 12, h - 84)]
        for x, y, sw, sh in slots:
            d.rectangle((x - 2, y - 2, x + sw + 1, y + sh + 1), outline=fg, width=2)
    elif kind == "meme":
        slots = [(0, 0, w, h)]
        title_y = 12
        cap_y = h - 32
    elif kind == "banner":
        slots = [(0, 0, w // 2, h)]
        title_x = w // 2 + 8
        title_y = 36
        cap_y = h - 32
        for x in range(w // 2, w, 8):
            d.line((x, 0, x - 80, h), fill=accent)
    elif kind == "poster":
        slots = [(26, 26, w - 52, h - 142)]
        title_y = h - 96
        cap_y = h - 48
        d.rectangle((23, 23, w - 24, h - 113), outline=fg, width=1)
    else:
        slots = [(w // 5, h // 5, w * 3 // 5, h * 3 // 5)]
        for _ in range({"sparse": 15, "balanced": 60, "chaotic": 150}[p.density]):
            x, y = rng.randrange(w), rng.randrange(h)
            size = rng.choice([2, 4, 7])
            d.rectangle((x, y, x + size, y + size), fill=accent)
        if p.style == "vaporwave":
            for y in range(h // 2, h, 16):
                d.line((0, y, w, y), fill=fg)
    for i, box in enumerate(slots):
        if images:
            paste(im, images[i % len(images)], box, p.fit)
        else:
            x, y, sw, sh = box
            d.rectangle((x, y, x + sw - 1, y + sh - 1), outline=accent)
            if sw >= 80 and sh >= 30:
                text(im, "YOUR IMAGE", (x + 4, y + sh // 2), fg)
    # Meme text gets a solid backing rather than antialiasing/blending.
    if kind == "meme":
        d.rectangle((0, 0, w, 30 * p.text_scale), fill="#000000")
        d.rectangle((0, cap_y - 4, w, h), fill="#000000")
    title_color = "#ffffff" if kind in ("window", "forum", "chat") else fg
    text(im, p.title, (title_x, title_y), title_color, p.text_scale, w - title_x - 8, p.exact_text)
    if p.caption:
        text(
            im,
            p.caption,
            (12 if kind != "web" else 126, cap_y),
            fg,
            1,
            w - (138 if kind == "web" else 24),
            p.exact_text,
        )
    return result(im, p.style, style=s, slots=slots, font="Pillow bundled 6x11 Latin-1 bitmap", seed=p.seed)


class CanvasParams(Params):
    image: ImageRef | None = None
    width: int = Field(640, ge=1, le=4096)
    height: int = Field(480, ge=1, le=4096)
    background: Color = "#ffffff"
    tile: bool = False

    @model_validator(mode="after")
    def bounded(self):
        if self.width * self.height > 8_000_000:
            raise ValueError("canvas exceeds 8 million pixels")
        return self


def canvas(p, im=None):
    out = Image.new("RGB", (p.width, p.height), color(p.background))
    if im:
        if p.tile:
            # Crop oversized tiles; reject pathological one-pixel iteration counts.
            if ((p.width + im.width - 1) // im.width) * ((p.height + im.height - 1) // im.height) > 65536:
                raise EngineError("too many tiles; enlarge the tile first")
            for y in range(0, p.height, im.height):
                for x in range(0, p.width, im.width):
                    paste(out, im, (x, y, im.width, im.height))
        else:
            paste(out, im, (0, 0, p.width, p.height))
    return result(out, "canvas")


class PaletteParams(Params):
    image: ImageRef
    palette: Literal["mono", "gameboy", "cga", "ega", "web", "custom"] = "ega"
    colors: list[Color] = Field(default_factory=list, max_length=256)
    dither: bool = True


def palette(p, im):
    colors = p.colors if p.palette == "custom" else PALETTES[p.palette]
    if not 2 <= len(colors) <= 256:
        raise EngineError("a palette needs 2 to 256 colors")
    rgb = [color(c)[:3] for c in colors]
    pal = Image.new("P", (1, 1))
    pal.putpalette(sum((list(c) for c in rgb), []) + list(rgb[-1]) * (256 - len(rgb)))
    source = im.convert("RGB")
    # Preserve alpha from the original below; an RGB color-key is invalid on the new palette.
    source.info.pop("transparency", None)
    out = source.quantize(
        palette=pal, dither=Image.Dither.FLOYDSTEINBERG if p.dither else Image.Dither.NONE
    )
    if im.mode in ('RGBA', 'LA') or 'transparency' in im.info:
        out = out.convert('RGBA')
        out.putalpha(im.convert('RGBA').getchannel('A').point(lambda a: 255 if a >= 128 else 0))
    return result(out, "palette", colors=colors)


class BitmapTextParams(Params):
    image: ImageRef
    text: str = Field(max_length=2000)
    x: int = Field(8, ge=0, le=4096)
    y: int = Field(8, ge=0, le=4096)
    color: Color = "#ffffff"
    scale: int = Field(1, ge=1, le=16)
    exact: bool = True


def bitmap_text(p, im):
    out = im.convert("RGBA")
    out.putalpha(out.getchannel('A').point(lambda a: 255 if a >= 128 else 0))
    text(out, p.text, (p.x, p.y), p.color, p.scale, out.width - p.x, p.exact)
    return result(out, "bitmap-text", font="Pillow bundled 6x11 Latin-1 bitmap")


class PatternParams(CanvasParams):
    pattern: Literal["checker", "stars", "scanlines", "grid", "confetti"] = "stars"
    foreground: Color = "#ffff00"
    spacing: int = Field(16, ge=2, le=256)
    seed: Seed = 1


def pattern(p, im=None):
    out = canvas(p, im).outputs[0].image
    d = ImageDraw.Draw(out)
    fg = color(p.foreground)
    s = p.spacing
    rng = random.Random(p.seed)
    for y in range(0, p.height, s):
        for x in range(0, p.width, s):
            if p.pattern == "checker" and (x // s + y // s) % 2 == 0:
                d.rectangle((x, y, x + s - 1, y + s - 1), fill=fg)
            elif p.pattern == "grid":
                d.line((x, y, x + s, y), fill=fg)
                d.line((x, y, x, y + s), fill=fg)
            elif p.pattern == "scanlines":
                d.line((x, y, x + s, y), fill=fg)
            elif p.pattern in ("stars", "confetti") and rng.random() < 0.35:
                dx, dy = x + rng.randrange(s), y + rng.randrange(s)
                d.line((dx - 2, dy, dx + 2, dy), fill=fg)
                if p.pattern == "stars":
                    d.line((dx, dy - 2, dx, dy + 2), fill=fg)
    return result(out, "pattern", seed=p.seed)


class AnimateStickerParams(Params):
    image: ImageRef
    sticker: ImageRef
    x: int = Field(0, ge=-4096, le=4096)
    y: int = Field(0, ge=-4096, le=4096)
    width: int = Field(88, ge=1, le=1024)
    frames: int = Field(8, ge=2, le=60)
    delay: int = Field(100, ge=20, le=2000)
    motion: Literal["still", "bounce", "blink", "scroll"] = "bounce"


def animate_sticker(p, base, sticker):
    if base.width * base.height * p.frames > 32_000_000:
        raise EngineError("animation exceeds 32 million frame pixels")
    ratio = p.width / sticker.width
    size = (p.width, max(1, round(sticker.height * ratio)))
    if size[1] > 4096:
        raise EngineError("sticker is too tall")
    # Pillow composites GIF disposal before yielding each frame. Uniform output timing is explicit.
    inputs = []
    for f in ImageSequence.Iterator(sticker):
        inputs.append(f.convert("RGBA").resize(size, Image.Resampling.NEAREST))
        if len(inputs) >= p.frames:
            break
    frames = []
    for i in range(p.frames):
        out = base.convert("RGB")
        x = p.x + (i * 4 if p.motion == "scroll" else 0)
        y = p.y + (abs(i * 2 - p.frames) * 2 if p.motion == "bounce" else 0)
        if p.motion != "blink" or i % 2 == 0:
            paste(out, inputs[i % len(inputs)], (x, y, *size))
        frames.append(out)
    return EngineResult(
        outputs=[Output("result", frames[0], "sticker.gif", fmt="GIF", frames=frames, duration=p.delay)],
        data={"frames": p.frames, "delay": p.delay, "loop": 0},
    )


EXPORTS = {
    "web-button": (88, 31),
    "blinkie": (150, 20),
    "forum-signature": (500, 150),
    "avatar": (100, 100),
    "wallpaper": (1024, 768),
    "original": None,
}


class ExportProfileParams(Params):
    image: ImageRef
    profile: Literal["web-button", "blinkie", "forum-signature", "avatar", "wallpaper", "original"] = (
        "original"
    )
    format: Literal["PNG", "JPEG", "GIF"] = "PNG"
    quality: int = Field(80, ge=1, le=100)
    max_bytes: int | None = Field(None, ge=100, le=50_000_000)
    fit: Literal["contain", "cover", "stretch"] = "contain"


def export_profile(p, im):
    size = EXPORTS[p.profile] or im.size
    out = Image.new("RGB", size, "#000000")
    paste(out, im, (0, 0, *size), p.fit)
    qualities = range(p.quality, 0, -1) if p.max_bytes and p.format == "JPEG" else [p.quality]
    for q in qualities:
        output = Output("result", out, "export." + p.format.lower(), fmt=p.format, quality=q)
        length = len(output.encode())
        if p.max_bytes is None or length <= p.max_bytes:
            return EngineResult(outputs=[output], data={"bytes": length, "quality": q, "profile": p.profile})
    raise EngineError(
        "the image cannot fit that byte limit at the requested dimensions",
        hint="increase the byte limit or choose a smaller profile",
    )
