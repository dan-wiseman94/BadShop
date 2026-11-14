from typing import Protocol

from PIL import Image

from badshop.engine.result import Output


class Store(Protocol):
    """Tool inputs and outputs: files for the CLI, artifacts for sessions."""

    def load(self, ref: str) -> Image.Image: ...

    def put(self, output: Output, stem: str) -> str: ...

    def export(self, ref: str, name: str | None) -> str: ...
