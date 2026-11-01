"""Deterministic composition layouts. Slot geometry is data; source pixels stay hard-edged."""

from copy import deepcopy
from typing import Annotated, Literal

from PIL import Image, ImageColor, ImageDraw, ImageOps
from pydantic import Field, model_validator

from badshop.engine.common import font
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.types import Box, Color, ImageRef, Params


def slot(name, box, caption, mask="rectangle"):
    return {"name": name, "box": list(box), "caption_box": list(caption), "mask": mask}


def grid(columns, rows, width, height, top=100, margin=24, gap=16, caption=48):
    cell_w = (width - margin * 2 - gap * (columns - 1)) // columns
    cell_h = (height - top - margin - gap * (rows - 1)) // rows
    return [slot(f"Image {i + 1}", (x, y, x + cell_w, y + cell_h - caption),
                 (x, y + cell_h - caption, x + cell_w, y + cell_h))
            for i in range(columns * rows)
            for x, y in [(margin + (i % columns) * (cell_w + gap), top + (i // columns) * (cell_h + gap))]]


LAYOUTS = {
    "trading-card": {"name": "Trading card", "width": 600, "height": 840, "background": "#f8db58", "accent": "#37214d",
                     "slots": [slot("Character", (35, 115, 565, 610), (45, 640, 555, 790))]},
    "character-select": {"name": "Character select", "width": 1000, "height": 720, "background": "#111b42", "accent": "#ffcc33",
                         "slots": grid(3, 2, 1000, 720)},
    "comic": {"name": "Two-panel conversation", "width": 1000, "height": 650, "background": "#ffffff", "accent": "#111111",
              "slots": grid(2, 1, 1000, 650, caption=115)},
    "newspaper": {"name": "Newspaper front page", "width": 760, "height": 1000, "background": "#f5efd9", "accent": "#171717",
                  "slots": [slot("Lead photo", (28, 140, 732, 600), (28, 608, 732, 686)),
                            slot("Inset left", (28, 710, 366, 910), (28, 914, 366, 976)),
                            slot("Inset right", (394, 710, 732, 910), (394, 914, 732, 976))]},
    "supermarket": {"name": "Supermarket flyer", "width": 800, "height": 1000, "background": "#ffff88", "accent": "#d81717",
                    "slots": grid(2, 3, 800, 1000, caption=55)},
    "inventory": {"name": "Game inventory", "width": 900, "height": 700, "background": "#333a36", "accent": "#c9ec97",
                  "slots": grid(4, 2, 900, 700)},
    "achievement": {"name": "Achievement popup", "width": 1000, "height": 280, "background": "#172d23", "accent": "#d1e384",
                    "slots": [slot("Badge", (28, 90, 188, 250), (215, 110, 965, 250), "ellipse")]},
    "yearbook": {"name": "Yearbook page", "width": 800, "height": 1000, "background": "#dbe3ec", "accent": "#273b64",
                 "slots": grid(3, 3, 800, 1000)},
    "certificate": {"name": "Certificate", "width": 1000, "height": 700, "background": "#fff9e6", "accent": "#6e421b",
                    "slots": [slot("Recipient", (390, 140, 610, 360), (120, 390, 880, 590), "ellipse")]},
    "classified": {"name": "Classified ads", "width": 900, "height": 900, "background": "#eeeecc", "accent": "#222222",
                   "slots": grid(3, 2, 900, 900, caption=140)},
    "sports-scoreboard": {"name": "Sports scoreboard", "width": 1000, "height": 600,
                          "background": "#0c2230", "accent": "#6eff66", "title_box": [32, 28, 968, 118],
                          "slots": [{**slot("Home team", (40, 180, 280, 420), (310, 245, 480, 420), "ellipse"), "caption_size": 84},
                                    {**slot("Away team", (720, 180, 960, 420), (520, 245, 690, 420), "ellipse"), "caption_size": 84}]},
    "desktop-error": {"name": "Desktop error dialog", "width": 920, "height": 620,
                      "background": "#008080", "accent": "#000080", "title_box": [82, 75, 800, 130],
                      "slots": [slot("Error icon", (105, 180, 285, 360), (320, 180, 805, 400))]},
    "product-box": {"name": "Cereal / product box", "width": 760, "height": 1000,
                    "background": "#fff4cf", "accent": "#a91719", "title_box": [42, 48, 550, 175],
                    "slots": [slot("Front of box", (60, 200, 545, 680), (52, 715, 550, 890)),
                              slot("Side-panel badge", (605, 110, 715, 220), (590, 250, 730, 620), "ellipse")]},
    "event-ticket": {"name": "Event ticket", "width": 1000, "height": 400,
                     "background": "#f9e4b7", "accent": "#741d32", "title_box": [30, 25, 710, 105],
                     "slots": [slot("Event artwork", (35, 125, 220, 335), (245, 125, 700, 345)),
                               slot("Stub badge", (785, 115, 925, 255), (770, 265, 950, 345))]},
    "tabloid-cover": {"name": "Tabloid cover", "width": 760, "height": 1000,
                      "background": "#ffff60", "accent": "#d41522", "title_box": [25, 20, 735, 130],
                      "slots": [{**slot("Cover star", (25, 170, 505, 740), (25, 765, 505, 970)), "caption_size": 46},
                                slot("Top teaser", (545, 175, 730, 380), (540, 390, 735, 530)),
                                slot("Bottom teaser", (545, 560, 730, 755), (540, 770, 735, 970))]},
    "restaurant-menu": {"name": "Restaurant menu", "width": 760, "height": 1000,
                        "background": "#fff8e7", "accent": "#174b37", "title_box": [32, 25, 728, 110],
                        "slots": [slot(f"Dish {i + 1}", (40, y, 190, y + 150),
                                       (220, y, 710, y + 155), "ellipse") for i, y in enumerate((160, 360, 560, 760))]},
}
TemplateName = Literal["trading-card", "character-select", "comic", "newspaper", "supermarket", "inventory",
                       "achievement", "yearbook", "certificate", "classified", "sports-scoreboard",
                       "desktop-error", "product-box", "event-ticket", "tabloid-cover", "restaurant-menu"]


class LayoutParams(Params):
    template: TemplateName = "trading-card"
    images: list[ImageRef] = Field(default_factory=list, max_length=12, description="Images in slot order; omit to make a blank layout")
    image_slots: list[Annotated[int, Field(ge=0, le=11)]] | None = Field(None, max_length=12, description="Optional zero-based slot index for each image; allows empty slots between images")
    title: str = Field("", max_length=300)
    captions: list[Annotated[str, Field(max_length=1000)]] = Field(default_factory=list, max_length=12)
    slots: list[Box] | None = Field(None, max_length=12, description="Optional replacement image boxes in canvas pixels; keep default order")
    fit: Literal["contain", "cover", "stretch"] = "contain"
    background: Color | None = None
    accent: Color | None = None

    @model_validator(mode="after")
    def valid_slots(self):
        definition = LAYOUTS[self.template]
        count = len(definition["slots"])
        if len(self.images) > count or len(self.captions) > count:
            raise ValueError(f"{self.template} has {count} slots")
        if self.image_slots is not None:
            if len(self.image_slots) != len(self.images) or len(set(self.image_slots)) != len(self.image_slots) or any(i >= count for i in self.image_slots):
                raise ValueError("image_slots must give one distinct valid slot index per image")
        if self.slots is not None:
            if len(self.slots) != count:
                raise ValueError(f"provide exactly {count} replacement slot boxes")
            for x1, y1, x2, y2 in self.slots:
                if not (0 <= x1 < x2 <= definition["width"] and 0 <= y1 < y2 <= definition["height"]):
                    raise ValueError("slot boxes must be nonempty and inside the canvas")
        return self


def definitions():
    return [{"id": key, **deepcopy(value), "max_images": len(value["slots"])} for key, value in LAYOUTS.items()]


def _caption(draw, box, text, color, size=34):
    """Wrap and shrink into a bounded text region; never write over an adjacent image slot."""
    if not text:
        return
    x1, y1, x2, y2 = box
    width, height = x2 - x1 - 12, y2 - y1 - 10
    if width < 1 or height < 1:
        return
    text = " ".join(text.split())
    lines = []
    for px in range(size, 7, -2):
        f = font(px)
        lines, line = [], ""
        # Character wrapping also handles URLs and unspaced words.
        for char in text:
            if draw.textbbox((0, 0), line + char, font=f)[2] > width and line:
                lines.append(line.rstrip())
                line = char.lstrip()
            else:
                line += char
        if line:
            lines.append(line)
        line_h = px + 3
        if len(lines) * line_h <= height:
            break
    max_lines = max(1, height // line_h)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-3] + "..."
    for i, line in enumerate(lines):
        draw.text((x1 + 6, y1 + 5 + i * line_h), line, font=f, fill=color, anchor="lt")


def _paste(canvas, image, box, fitting, shape):
    x1, y1, x2, y2 = box
    size = (x2 - x1, y2 - y1)
    image = image.convert("RGBA")
    if fitting == "stretch":
        piece = image.resize(size, Image.Resampling.NEAREST)
    elif fitting == "cover":
        piece = ImageOps.fit(image, size, method=Image.Resampling.NEAREST)
    else:
        fitted = ImageOps.contain(image, size, method=Image.Resampling.NEAREST)
        piece = Image.new("RGBA", size)
        piece.paste(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
    mask = piece.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
    if shape == "ellipse":
        shape_mask = Image.new("L", size)
        ImageDraw.Draw(shape_mask).ellipse((0, 0, size[0] - 1, size[1] - 1), fill=255)
        from PIL import ImageChops
        mask = ImageChops.multiply(mask, shape_mask)
    canvas.paste(piece.convert("RGB"), (x1, y1), mask)


def _decoration(draw, template, size, bg, accent):
    """Hard geometric furniture gives each format its own visual structure."""
    width, height = size
    if template == "sports-scoreboard":
        draw.rectangle((16, 16, width - 17, height - 17), outline=accent, width=8)
        draw.line((30, 140, 970, 140), fill=accent, width=5)
        draw.rectangle((300, 165, 700, 435), fill="#050a0e", outline=accent, width=3)
        for y in (260, 295):
            draw.rectangle((493, y, 507, y + 14), fill=accent)
        _caption(draw, (50, 460, 280, 530), "HOME", accent, 34)
        _caption(draw, (725, 460, 955, 530), "AWAY", accent, 34)
        for x in range(50, 960, 30):
            draw.rectangle((x, 555, x + 10, 565), fill=accent)
    elif template == "desktop-error":
        draw.rectangle((60, 60, 860, 560), fill="#c0c0c0", outline="black", width=3)
        draw.line([(64, 555), (64, 64), (855, 64)], fill="white", width=5)
        draw.line([(68, 554), (854, 554), (854, 68)], fill="#444444", width=5)
        draw.rectangle((73, 73, 846, 135), fill=accent)
        draw.rectangle((807, 84, 834, 119), fill="#c0c0c0", outline="white", width=2)
        draw.line((814, 92, 828, 111), fill="black", width=3)
        draw.line((828, 92, 814, 111), fill="black", width=3)
        for x, label in ((260, "RETRY"), (450, "IGNORE"), (640, "PANIC")):
            draw.rectangle((x, 457, x + 150, 515), fill="#c0c0c0", outline="black", width=2)
            draw.line([(x + 2, 513), (x + 2, 459), (x + 148, 459)], fill="white", width=3)
            _caption(draw, (x + 12, 467, x + 142, 508), label, "black", 22)
    elif template == "product-box":
        draw.rectangle((24, 24, 568, 976), outline=accent, width=6)
        draw.rectangle((580, 24, 736, 976), outline=accent, width=4)
        for x in range(30, 565, 20):
            draw.polygon([(x, 26), (x + 10, 42), (x + 20, 26)], fill=accent)
        draw.line((580, 50, 736, 50), fill=accent, width=3)
        draw.rectangle((591, 670, 725, 925), outline=accent, width=3)
        _caption(draw, (594, 676, 722, 725), "FACTS", accent, 24)
        for y in range(730, 920, 30):
            draw.line((596, y, 721, y), fill=accent, width=2)
        for index, x in enumerate(range(85, 510, 7)):
            draw.rectangle((x, 916, x + (2 if index % 3 else 4), 955), fill=accent)
    elif template == "event-ticket":
        draw.rectangle((12, 12, 987, 387), outline=accent, width=5)
        for y in range(20, 385, 18):
            draw.line((738, y, 738, min(y + 8, 380)), fill=accent, width=3)
        for x in (0, 999):
            draw.ellipse((x - 18, 180, x + 18, 220), fill=accent)
            draw.ellipse((x - 13, 185, x + 13, 215), fill=bg)
        _caption(draw, (765, 35, 960, 90), "ADMIT ONE", accent, 25)
        for index, x in enumerate(range(775, 945, 6)):
            draw.rectangle((x, 355, x + (1 if index % 3 else 3), 375), fill=accent)
    elif template == "tabloid-cover":
        draw.rectangle((10, 10, 749, 145), fill=accent)
        draw.line((524, 158, 524, 980), fill=accent, width=8)
        draw.line((538, 545, 740, 545), fill=accent, width=7)
        draw.rectangle((12, 153, 748, 986), outline=accent, width=4)
    elif template == "restaurant-menu":
        draw.rectangle((13, 13, 746, 986), outline=accent, width=3)
        draw.line((30, 125, 730, 125), fill=accent, width=4)
        for y in (335, 535, 735):
            draw.line((220, y, 710, y), fill=accent, width=2)
        for x in range(30, 730, 24):
            draw.rectangle((x, 950, x + 12, 962), fill=accent)
            draw.rectangle((x + 12, 962, x + 24, 974), fill=accent)
    else:
        draw.rectangle((9, 9, width - 10, height - 10), outline=accent, width=5)


def render(p: LayoutParams, images: list[Image.Image]) -> EngineResult:
    definition = deepcopy(LAYOUTS[p.template])
    if p.slots:
        for item, box in zip(definition["slots"], p.slots, strict=True):
            item["box"] = list(box)
    try:
        bg = ImageColor.getrgb(p.background or definition["background"])
        accent = ImageColor.getrgb(p.accent or definition["accent"])
    except ValueError as e:
        raise EngineError(f"invalid layout color: {e}") from None
    canvas = Image.new("RGB", (definition["width"], definition["height"]), bg)
    draw = ImageDraw.Draw(canvas)
    draw.fontmode = "1"
    _decoration(draw, p.template, canvas.size, bg, accent)
    title_color = "white" if p.template in ("desktop-error", "tabloid-cover") else accent
    _caption(draw, definition.get("title_box", (24, 20, canvas.width - 24, 90)),
             p.title or definition["name"].upper(), title_color, 45)
    mapped = dict(zip(p.image_slots if p.image_slots is not None else range(len(images)), images, strict=True))
    for index, item in enumerate(definition["slots"]):
        x1, y1, x2, y2 = item["box"]
        draw.rectangle((x1 - 3, y1 - 3, x2 + 2, y2 + 2), outline=accent, width=3)
        if index in mapped:
            _paste(canvas, mapped[index], item["box"], p.fit, item["mask"])
        else:
            _caption(draw, item["box"], item["name"], accent, 22)
        caption = p.captions[index] if index < len(p.captions) else ""
        _caption(draw, item["caption_box"], caption, accent, item.get("caption_size", 28))
    return EngineResult(outputs=[Output("layout", canvas, f"{p.template}.png")],
        lines=[f"{definition['name']}: {len(images)} images in {len(definition['slots'])} editable slots"],
        data={"layout": {"id": p.template, **definition}})
