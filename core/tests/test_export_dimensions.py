import io

import pytest
from PIL import Image
from pydantic import ValidationError

from badshop.engine.retro import ExportProfileParams, export_profile


def test_custom_export_contains_source_with_chosen_matte():
    source = Image.new("RGB", (8, 4), "red")
    params = ExportProfileParams(image="source", width=20, height=20, background="#ffffff")
    encoded = export_profile(params, source).outputs[0].encode()
    with Image.open(io.BytesIO(encoded)) as image:
        assert image.size == (20, 20)
        assert image.getpixel((0, 0)) == (255, 255, 255)
        assert image.getpixel((10, 10)) == (255, 0, 0)
    assert source.size == (8, 4)


def test_custom_export_requires_both_bounded_dimensions():
    with pytest.raises(ValidationError, match="both"):
        ExportProfileParams(image="source", width=20)
    with pytest.raises(ValidationError):
        ExportProfileParams(image="source", width=2001, height=20)


def test_animation_export_preserves_timing_loop_and_input_position():
    buf = io.BytesIO()
    Image.new("RGB", (20, 10), "red").save(buf, "GIF", save_all=True,
        append_images=[Image.new("RGB", (20, 10), "blue")], duration=[80, 170], loop=3)
    with Image.open(io.BytesIO(buf.getvalue())) as source:
        source.seek(1)
        output = export_profile(ExportProfileParams(image="source", format="GIF",
            preserve_animation=True, width=10, height=10), source).outputs[0]
        assert source.tell() == 1
        with Image.open(io.BytesIO(output.encode())) as result:
            assert result.n_frames == 2
            assert result.size == (10, 10)
            assert result.info["loop"] == 3
            assert result.info["duration"] == 80
            result.seek(1)
            assert result.info["duration"] == 170
            assert result.convert("RGB").getpixel((5, 5)) == (0, 0, 255)


def test_png_budget_can_reduce_dimensions_without_changing_source():
    source = Image.effect_noise((100, 100), 100).convert("RGB")
    result = export_profile(ExportProfileParams(image="source", format="PNG",
        max_bytes=1000, shrink_to_fit=True), source).outputs[0]
    assert len(result.encode()) <= 1000
    assert result.image.width < 100
    assert source.size == (100, 100)


def test_export_presets_persist_validated_settings_without_project_references(tmp_path, monkeypatch):
    from badshop.server.settings import ExportPreset, Settings, load_settings, save_settings
    monkeypatch.setenv("BADSHOP_CONFIG_DIR", str(tmp_path))
    preset = ExportPreset(name=" Chat attachment ", params={"width": 240, "height": 160, "max_bytes": 50000})
    save_settings(Settings(export_presets=[preset]))
    assert load_settings().export_presets == [preset]
    assert preset.name == "Chat attachment"
    assert "image" not in preset.params
    with pytest.raises(ValidationError, match="project image"):
        ExportPreset(name="Bad", params={"image": "source"})
    with pytest.raises(ValidationError, match="both"):
        ExportPreset(name="Bad", params={"width": 240})
    with pytest.raises(ValidationError):
        Settings(export_presets=[preset] * 31)
