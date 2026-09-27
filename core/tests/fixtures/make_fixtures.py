"""Regenerate the committed test images and recorded API responses. Needs internet.

Run: uv run python tests/fixtures/make_fixtures.py
"""

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
API = {
    "commons.json": "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": "golden retriever filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 8,
        "prop": "imageinfo", "iiprop": "url|mime|size", "iiurlwidth": 1200}),
    "openverse.json": "https://api.openverse.org/v1/images/?q=golden+retriever&page_size=8&mature=false",
    "wiki.json": "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search", "gsrsearch": "Abraham Lincoln",
        "gsrnamespace": 0, "gsrlimit": 6, "prop": "pageimages", "piprop": "thumbnail",
        "pithumbsize": 1200, "pilimit": "max"}),
    "imgflip.json": "https://api.imgflip.com/get_memes",
}


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def commons_thumb(title: str, width: int = 600) -> bytes:
    q = urllib.parse.urlencode({"action": "query", "format": "json", "titles": f"File:{title}",
                                "prop": "imageinfo", "iiprop": "url", "iiurlwidth": width})
    pages = json.loads(get(f"https://commons.wikimedia.org/w/api.php?{q}"))["query"]["pages"]
    return get(next(iter(pages.values()))["imageinfo"][0]["thumburl"])


def record_api() -> None:
    d = HERE / "api"
    d.mkdir(exist_ok=True)
    for name, url in API.items():
        (d / name).write_bytes(get(url))
        print("api/" + name)
    (d / "page.html").write_text(
        '<html><head><meta property="og:image" content="/images/lincoln.png"></head><body>hi</body></html>')


def main() -> None:
    for name, title in COMMONS.items():
        im = Image.open(io.BytesIO(commons_thumb(title))).convert("RGB")
        im.thumbnail((600, 600))
        im.save(HERE / name)
        print(name, im.size)
    Image.open(io.BytesIO(get(TWEMOJI_JOY))).convert("RGBA").save(HERE / "emoji_joy.png")
    print("emoji_joy.png")
    record_api()


if __name__ == "__main__":
    main()
