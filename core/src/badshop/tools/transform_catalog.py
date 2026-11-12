"""Manual geometry uses the same tool registry as agent and CLI execution."""

from badshop.engine.transform import TransformParams, transform
from badshop.tools.registry import ToolSpec, register

register(ToolSpec(
    name="transform", params=TransformParams, category="edit",
    run=lambda p, store: transform(p, store.load(p.image)),
    summary="crop, resize, rotate or flip an image",
    description="Crop inside the image, resize with nearest-neighbor sampling, flip, then rotate "
                "counter-clockwise in quarter turns. Omit one resize dimension to preserve aspect ratio. "
                "Both dimensions must fit within 1000 pixels. No blending or generated pixels.",
))
