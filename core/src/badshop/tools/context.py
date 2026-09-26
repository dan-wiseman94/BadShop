from typing import Protocol

from PIL import Image

from badshop.engine.result import Output


class Store(Protocol):
    """Where tool inputs come from and outputs go. The CLI uses files; sessions (Plan 2) use artifacts."""

    def load(self, ref: str) -> Image.Image: ...

    def put(self, output: Output, stem: str) -> str: ...

    def export(self, ref: str, name: str | None) -> str: ...
