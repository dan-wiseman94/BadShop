"""What every engine function returns."""

import io
from dataclasses import dataclass, field

from PIL import Image

EXT = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "WEBP": ".webp"}


@dataclass
class Output:
    key: str  # printed label: "result", "work", "grid", "saved", "1"...
    image: Image.Image
    name_hint: str  # "result.png", "{stem}_work.png", "fetch/x_1.jpg", or "final:<stem>" (no extension)
    fmt: str = "PNG"
    quality: int | None = None
    frames: list[Image.Image] | None = None  # animated GIF frames; image is frames[0]
    duration: int | None = None
    caption: str = ""  # printed after the path on the same line

    def ext(self) -> str:
        return EXT[self.fmt]

    def encode(self) -> bytes:
        buf = io.BytesIO()
        if self.frames:
            self.frames[0].save(buf, "GIF", save_all=True, append_images=self.frames[1:],
                                duration=self.duration, loop=0, optimize=False)
        elif self.fmt == "JPEG":
            kw = {"quality": self.quality} if self.quality is not None else {}
            self.image.save(buf, "JPEG", **kw)
        else:
            self.image.save(buf, self.fmt)
        return buf.getvalue()


@dataclass
class EngineResult:
    outputs: list[Output] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)
