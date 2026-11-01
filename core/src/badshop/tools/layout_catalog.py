"""Layout tool registration, kept separate from the original CLI parity catalog."""
from badshop.engine import layouts
from badshop.tools.registry import ToolSpec, register

register(ToolSpec(
    name="layout", params=layouts.LayoutParams, category="compose",
    run=lambda p, store: layouts.render(p, [store.load(ref) for ref in p.images]),
    summary="compose images into editable cards, comics, newspapers, flyers and more",
    description="Build a deterministic composition with named image slots and caption regions. Choose template, "
                "provide images and captions in slot order, and a title. Missing images leave labeled placeholders. "
                "Optional slots replaces the image boxes; output structured layout data gives all coordinates. "
                "fit=contain keeps whole images, cover crops to fill, stretch deliberately distorts. All image "
                "scaling uses nearest-neighbor and masks are hard. Use this for actual layouts rather than guessing coordinates.",
))
