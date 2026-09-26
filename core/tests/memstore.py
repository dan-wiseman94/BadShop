from pathlib import Path

from PIL import Image

from badshop.engine.errors import EngineError
from badshop.engine.result import Output


class MemoryStore:
    """In-memory Store for unit tests. Refs look like `mem:3/name.png` so stems stay meaningful."""

    def __init__(self):
        self.images: dict[str, Image.Image] = {}
        self.outputs: dict[str, Output] = {}
        self.exported: list[tuple[str, str | None]] = []

    def add(self, image: Image.Image, name: str = "x.png") -> str:
        ref = f"mem:{len(self.images)}/{name}"
        self.images[ref] = image
        return ref

    def load(self, ref: str) -> Image.Image:
        if ref not in self.images:
            raise EngineError(f"no such image: {ref}")
        return self.images[ref].copy()

    def put(self, output: Output, stem: str) -> str:
        ref = self.add(output.image, Path(output.name_hint.replace("{stem}", stem)).name)
        self.outputs[ref] = output
        return ref

    def export(self, ref: str, name: str | None) -> str:
        self.exported.append((ref, name))
        return f"exported/{name or 'x'}"
