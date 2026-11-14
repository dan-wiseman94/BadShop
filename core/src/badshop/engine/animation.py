"""Bounded, replayable edits to an existing short animation."""

from PIL import Image
from pydantic import Field

from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult, Output
from badshop.engine.retro import BitmapTextParams, bitmap_text
from badshop.engine.types import Box, Color, ImageRef, Params

MAX_FRAMES = 200
MAX_PIXELS = 20_000_000


class AnimationFrame(Params):
    index: int = Field(ge=0, lt=MAX_FRAMES)
    duration: int | None = Field(None, ge=10, le=10000, description="milliseconds; omit to keep source timing")


class AnimationCaption(Params):
    text: str = Field(min_length=1, max_length=1000)
    start: int = Field(0, ge=0, lt=MAX_FRAMES, description="first output frame, zero based")
    end: int = Field(ge=1, le=MAX_FRAMES, description="exclusive last output frame")
    x: int = Field(8, ge=0, le=2000)
    y: int = Field(8, ge=0, le=2000)
    scale: int = Field(1, ge=1, le=16)
    color: Color = "#ffffff"


class AnimationEditParams(Params):
    image: ImageRef
    frames: list[AnimationFrame] | None = Field(None, min_length=1, max_length=MAX_FRAMES,
        description="output order; repeat indices to duplicate; omit to keep all frames")
    crop: Box | None = None
    speed: float = Field(1, ge=0.1, le=10, multiple_of=0.1, description="2 is twice as fast; 0.5 is half speed")
    captions: list[AnimationCaption] = Field(default_factory=list, max_length=12)
    loop: int | None = Field(None, ge=0, le=65535, description="omit to keep source; zero loops forever")


def edit(p: AnimationEditParams, image: Image.Image) -> EngineResult:
    count = getattr(image, "n_frames", 1)
    if count > MAX_FRAMES or image.width * image.height * count > MAX_PIXELS:
        raise EngineError("animation exceeds 200 frames or 20 million decoded pixels", hint="import a shorter or smaller clip")
    sequence = p.frames if p.frames is not None else [AnimationFrame(index=i) for i in range(count)]
    if any(frame.index >= count for frame in sequence):
        raise EngineError("selected frame is outside this animation")
    x1, y1, x2, y2 = p.crop or (0, 0, image.width, image.height)
    if not (0 <= x1 < x2 <= image.width and 0 <= y1 < y2 <= image.height):
        raise EngineError("animation crop must be a positive box inside the source")
    if (x2 - x1) * (y2 - y1) * len(sequence) > MAX_PIXELS:
        raise EngineError("edited animation exceeds 20 million output pixels")
    for caption in p.captions:
        if not 0 <= caption.start < caption.end <= len(sequence):
            raise EngineError("caption range must fit inside the output frame sequence")
    position = image.tell()
    loop = image.info.get("loop", 0) if p.loop is None else p.loop
    decoded = {}
    durations = {}
    try:
        # Decode sequentially once, respecting GIF disposal/composited frame semantics.
        for index in range(count):
            image.seek(index)
            if any(frame.index == index for frame in sequence):
                frame = image.convert("RGBA").crop((x1, y1, x2, y2))
                frame.putalpha(frame.getchannel("A").point(lambda a: 255 if a >= 128 else 0))
                decoded[index] = frame
                durations[index] = max(10, int(image.info.get("duration", 100) or 100))
    finally:
        image.seek(position)
    output, timing = [], []
    for index, selection in enumerate(sequence):
        frame = decoded[selection.index].copy()
        for caption in p.captions:
            if caption.start <= index < caption.end:
                params = BitmapTextParams(image=p.image, **caption.model_dump(exclude={"start", "end"}))
                frame = bitmap_text(params, frame).outputs[0].image
        delay = (selection.duration if selection.duration is not None else durations[selection.index]) / p.speed
        if delay > 655350:
            raise EngineError("frame duration exceeds the GIF limit", hint="increase speed or shorten the hold")
        timing.append(max(10, round(delay / 10) * 10))
        output.append(frame)
    if sum(timing) > 655350:
        raise EngineError("edited animation exceeds the short GIF duration limit of 655 seconds")
    return EngineResult(outputs=[Output("result", output[0], "edited.gif", fmt="GIF", frames=output,
        duration=timing, loop=loop)], data={"frames": len(output), "durations": timing,
            "source_frames": [frame.index for frame in sequence], "loop": loop},
        lines=[f"Edited {len(output)} frames; {sum(timing)} ms; {x2 - x1}x{y2 - y1}"])
