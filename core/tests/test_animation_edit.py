import io

import pytest
from PIL import Image
from pydantic import ValidationError

from badshop.engine.animation import AnimationEditParams, edit
from badshop.engine.errors import EngineError


def animation(size=(80, 40)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, "GIF", save_all=True,
        append_images=[Image.new("RGB", size, color) for color in ("green", "blue")],
        duration=[80, 170, 240], loop=3)
    return Image.open(io.BytesIO(buffer.getvalue()))


def test_animation_sequence_crop_timing_captions_and_source_position():
    with animation() as source:
        source.seek(1)
        params = AnimationEditParams(image="source", crop=[10, 5, 70, 35], speed=2,
            frames=[{"index": 2}, {"index": 0, "duration": 1000}, {"index": 1}],
            captions=[{"text": "Hi", "start": 1, "end": 2, "x": 1, "y": 1}])
        result = edit(params, source)
        assert source.tell() == 1
        assert result.data["durations"] == [120, 500, 80]
        with Image.open(io.BytesIO(result.outputs[0].encode())) as output:
            assert output.size == (60, 30)
            assert output.n_frames == 3
            assert output.info["loop"] == 3
            assert output.convert("RGB").getpixel((0, 0)) == (0, 0, 255)
            output.seek(1)
            assert output.info["duration"] == 500
            assert output.convert("RGB").getpixel((0, 0)) == (255, 0, 0)
            assert (255, 255, 255) in output.convert("RGB").get_flattened_data()
            output.seek(2)
            assert set(output.convert("RGB").get_flattened_data()) == {(0, 128, 0)}
        assert edit(params, source).outputs[0].encode() == result.outputs[0].encode()


def test_animation_duplicate_preserves_total_hold_and_default_timings():
    with animation() as source:
        result = edit(AnimationEditParams(image="source"), source)
        assert result.data["durations"] == [80, 170, 240]
        result = edit(AnimationEditParams(image="source", frames=[{"index": 0}, {"index": 0}, {"index": 2}]), source)
        with Image.open(io.BytesIO(result.outputs[0].encode())) as output:
            # GIF encoders merge identical adjacent frames into one equivalent hold.
            assert output.info["duration"] == 160
            output.seek(1)
            assert output.info["duration"] == 240


@pytest.mark.parametrize("patch, message", [
    ({"frames": [{"index": 4}]}, "outside"),
    ({"crop": [-1, 0, 20, 20]}, "crop"),
    ({"captions": [{"text": "no", "start": 2, "end": 1}]}, "range"),
])
def test_animation_invalid_edit_keeps_source(patch, message):
    with animation() as source:
        source.seek(1)
        with pytest.raises(EngineError, match=message):
            edit(AnimationEditParams(image="source", **patch), source)
        assert source.tell() == 1


def test_animation_resource_bounds_before_frame_allocation():
    with pytest.raises(ValidationError):
        AnimationEditParams(image="source", frames=[{"index": 0}] * 201)
    with animation((3000, 3000)) as source:
        with pytest.raises(EngineError, match="decoded pixels"):
            edit(AnimationEditParams(image="source"), source)
    with animation() as source:
        with pytest.raises(EngineError, match="duration limit"):
            edit(AnimationEditParams(image="source", speed=0.1,
                frames=[{"index": 0, "duration": 10000}] * 7), source)
