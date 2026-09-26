"""Regenerate the committed test images. Needs internet. Run: uv run python tests/fixtures/make_fixtures.py"""

import io
import json
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
UA = {"User-Agent": "badshop-tests/0.1 (fixture generator)"}
COMMONS = {  # both public domain; see LICENSES.md
    "lincoln.png": "Abraham Lincoln head on shoulders photo portrait.jpg",
    "trump.png": "Donald Trump official portrait.jpg",
}
TWEMOJI_JOY = "https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72/1f602.png"


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def commons_thumb(title: str, width: int = 600) -> bytes:
    q = urllib.parse.urlencode({"action": "query", "format": "json", "titles": f"File:{title}",
                                "prop": "imageinfo", "iiprop": "url", "iiurlwidth": width})
    pages = json.loads(get(f"https://commons.wikimedia.org/w/api.php?{q}"))["query"]["pages"]
    return get(next(iter(pages.values()))["imageinfo"][0]["thumburl"])


def main() -> None:
    for name, title in COMMONS.items():
        im = Image.open(io.BytesIO(commons_thumb(title))).convert("RGB")
        im.thumbnail((600, 600))
        im.save(HERE / name)
        print(name, im.size)
    Image.open(io.BytesIO(get(TWEMOJI_JOY))).convert("RGBA").save(HERE / "emoji_joy.png")
    print("emoji_joy.png")


if __name__ == "__main__":
    main()
