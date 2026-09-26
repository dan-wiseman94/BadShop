"""Every tool, registered once, with the description an LLM sees."""

from badshop.engine import basic, text
from badshop.tools.registry import ToolSpec, register

register(ToolSpec(
    name="info", params=basic.InfoParams, category="inspect", mutates=False, read_only=True,
    run=lambda p, s: basic.info(p, s.load(p.image)),
    summary="print an image's size",
    description="Report an image's width and height in pixels. Cheap; use it before choosing coordinates.",
))

register(ToolSpec(
    name="prep", params=basic.PrepParams, category="inspect",
    run=lambda p, s: basic.prep(p, s.load(p.image)),
    summary="make a small working copy plus a gridded copy",
    description=("Make a working copy no larger than `max` px on its longest side, plus a copy with labeled "
                 "pixel gridlines. Work only with the working copy afterwards so coordinates you read "
                 "match what the tools use."),
))

register(ToolSpec(
    name="view", params=basic.ViewParams, category="inspect", mutates=False, read_only=True,
    run=lambda p, s: basic.view(p, s.load(p.image)),
    summary="look at an image, optionally with a coordinate grid",
    description=("Return an image so you can see it. Set grid=true to overlay labeled pixel gridlines "
                 "(every 50 px, labels every 100) when you need to read coordinates. Views larger than "
                 "`max` are scaled down and say so; convert coordinates back before using them."),
))

register(ToolSpec(
    name="text", params=text.TextParams, category="text",
    run=lambda p, s: text.caption(p, s.load(p.image)),
    summary="Impact caption, MS Paint text, or WordArt",
    description=("Write a caption. Default: Impact meme style, white with black outline, uppercase, "
                 "auto-sized, at the top; bottom=true for the punchline. style=paint is colored text with a "
                 "hard shadow (looks drawn in MS Paint); style=wordart is a rainbow face with a 3D "
                 "extrusion. at=[x,y] centers the text anywhere. A literal \\n forces a line break."),
))
