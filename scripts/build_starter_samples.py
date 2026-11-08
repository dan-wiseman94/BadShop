"""Rebuild original, CC0 starter art and previews through BadShop's ordinary layout engine.

Run: uv run --project core python scripts/build_starter_samples.py
No network, models, platform fonts or third-party image rights are required.
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw
from badshop.engine.layouts import LAYOUTS, LayoutParams, render

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / "app/public/samples"
    destination.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (80, 80), "#ffc856")
    draw = ImageDraw.Draw(im)
    # Original geometric pigeon: deliberately stepped contours and nearest-neighbor pixels.
    draw.rectangle((0, 63, 79, 79), fill="#81b7b1")
    draw.polygon([(16, 56), (24, 35), (42, 29), (48, 14), (62, 14), (68, 20), (68, 37),
                  (60, 42), (55, 59), (39, 66), (23, 64)], fill="#565770")
    draw.rectangle((49, 20, 62, 34), fill="#a1a2b1")
    draw.rectangle((55, 23, 60, 27), fill="#fff4d3")
    draw.rectangle((58, 23, 59, 24), fill="#141622")
    draw.polygon([(63, 30), (75, 34), (63, 35)], fill="#ed754f")
    draw.polygon([(22, 47), (42, 39), (51, 45), (41, 59), (28, 61)], fill="#818398")
    draw.rectangle((44, 35, 57, 40), fill="#668f84")
    draw.line((35, 64, 35, 70, 29, 70), fill="#b54450", width=3)
    draw.line((47, 63, 47, 70, 53, 70), fill="#b54450", width=3)
    im = im.resize((640, 640), Image.Resampling.NEAREST)
    im.save(destination / "pigeon.png")
    for starter in json.loads((ROOT / "app/src/starters.json").read_text()):
        count = len(LAYOUTS[starter["template"]]["slots"])
        captions = [starter["caption"], starter.get("secondCaption", "Probably fine.")] + [""] * 10
        params = LayoutParams(template=starter["template"], title=starter["title"], captions=captions[:count])
        image = render(params, [im] * count).outputs[0].image
        image.thumbnail((300, 230), Image.Resampling.NEAREST)
        image.save(destination / f'{starter["template"]}.png')


if __name__ == "__main__":
    main()
