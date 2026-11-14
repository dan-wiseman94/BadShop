import io
import asyncio
import threading
import json
import pytest
from PIL import Image
from pydantic import ValidationError

from badshop.engine import retro, collections, discovery, assets
from badshop.engine.errors import EngineError
from badshop.session import branches, project, recipes, netpolicy
from badshop.session.models import Source
from badshop.session.session import Session
from badshop.session.execution import execute_call, ToolCall
from badshop.session.preferences import CreativePreferences
from test_server_app import env as env


def imported(session, color="red", source=None):
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "PNG")
    return session.artifacts.add(buf.getvalue(), color, source=source).id


@pytest.mark.parametrize("style", retro.STYLES)
def test_retro_layouts_are_deterministic_and_keep_exact_size(style):
    p = retro.RetroParams(style=style, title="TEST", seed=7)
    source = Image.new("RGBA", (13, 7), (127, 34, 56, 127))
    a = retro.render(p, [source]).outputs[0]
    b = retro.render(p, [source]).outputs[0]
    assert a.encode() == b.encode()
    assert a.image.size == (retro.STYLES[style]["width"], retro.STYLES[style]["height"])
    assert (127, 34, 56) not in a.image.getdata()  # half-transparent pixels never blend


def test_exact_bitmap_caption_fails_without_silent_rewrite():
    with pytest.raises(EngineError, match="fit"):
        retro.render(retro.RetroParams(style="badge", title="too long to fit in this button"), [])
    with pytest.raises(EngineError, match="Latin-1"):
        retro.render(retro.RetroParams(title="🐈"), [])


def test_palette_contains_only_selected_colors_and_export_limits():
    image = Image.linear_gradient("L").convert("RGB")
    out = retro.palette(retro.PaletteParams(image="x", palette="cga"), image).outputs[0].image.convert("RGB")
    assert set(out.getdata()) <= set(map(retro.color, retro.PALETTES["cga"]))
    output = retro.export_profile(retro.ExportProfileParams(image="x", profile="web-button"), image).outputs[
        0
    ]
    assert output.image.size == (88, 31)
    with pytest.raises(EngineError, match="byte limit"):
        retro.export_profile(retro.ExportProfileParams(image="x", max_bytes=100), image)


def test_palette_replaces_transparent_gif_palette_without_losing_the_mask():
    image = Image.new("P", (3, 1))
    image.putpalette([255, 0, 0, 0, 255, 0] + [0] * 762)
    image.putdata([0, 1, 0])
    image.info["transparency"] = 0
    out = retro.palette(retro.PaletteParams(image="gif", palette="cga"), image).outputs[0].image
    assert list(out.getchannel("A").get_flattened_data()) == [0, 255, 0]
    assert image.info["transparency"] == 0


@pytest.mark.parametrize("trigger", ["disconnect", "cancel"])
def test_recipe_request_ends_owned_work_and_releases_its_reservation(env, monkeypatch, trigger):
    from badshop.server.app import CoreApp
    from badshop.server.settings import Settings
    from badshop.session.execution import InProcessExecutor
    from test_server_app import Client

    async def scenario():
        app = CoreApp(Settings(), executor_factory=lambda **_: InProcessExecutor())
        client = Client(app)
        entered = threading.Event()
        finished = threading.Event()
        recipe = {"name": "canvas", "steps": [{"tool": "canvas", "params": {"width": 16, "height": 16}}]}
        aid = imported(app.session)

        def run(session, parsed, inputs, signal):
            entered.set()
            assert signal.wait(5), "owned recipe did not receive cancellation"
            finished.set()
            return {"completed": [], "errors": [], "rows": [], "cancelled": True}

        monkeypatch.setattr(recipes, "run", run)
        pending = asyncio.create_task(client.call("recipes.run", recipe=recipe, inputs=[aid]))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            if trigger == "disconnect":
                app.on_client_gone()
                assert (await pending)["cancelled"]
            else:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            assert finished.is_set() and app._recipe_cancel is None
            app._check_idle()
            assert not app.session.data.steps
        finally:
            if app._recipe_cancel is not None:
                app._recipe_cancel.set()
            await asyncio.gather(pending, return_exceptions=True)
            client.unsubscribe()
            await app.close()

    asyncio.run(scenario())


def test_new_projects_copy_style_defaults_without_dangling_image_pins(env):
    from badshop.server.app import CoreApp
    from badshop.server.settings import Settings
    from badshop.session.execution import InProcessExecutor

    async def scenario():
        defaults = CreativePreferences(style="forum", source_roles={"subject": "a" * 64})
        app = CoreApp(Settings(creative_defaults=defaults), executor_factory=lambda **_: InProcessExecutor())
        try:
            assert app.session.data.creative.style == "forum"
            assert app.session.data.creative.source_roles == {}
            await app._session_save_as("user", str(env / "new.badshop"))
            assert project.open_project(env / "new.badshop").data.creative.source_roles == {}
        finally:
            await app.close()

    asyncio.run(scenario())


def test_animation_frames_do_not_leave_trails():
    base = Image.new("RGB", (30, 30), "black")
    sticker = Image.new("RGBA", (3, 3), "red")
    p = retro.AnimateStickerParams(image="base", sticker="sticker", frames=4, width=3, motion="scroll")
    data = retro.animate_sticker(p, base, sticker).outputs[0].encode()
    im = Image.open(io.BytesIO(data))
    assert im.n_frames == 4
    im.seek(3)
    assert im.convert("RGB").getpixel((0, 0)) == (0, 0, 0)
    assert im.convert("RGB").getpixel((12, 0)) == (255, 0, 0)
    assert im.info["duration"] == 100


def test_preferences_branches_recipes_reopen_and_old_schema(tmp_path):
    s = Session.new()
    aid = imported(s)
    s.data.creative = CreativePreferences(
        style="forum", seed=42, favorite_styles=["badge"], mixer={"era": "desktop"}
    )
    original = s.run_tool("retro_layout", {"images": [aid], "title": "HELLO"}, "user")
    assert original.status == "done" and original.params["style"] == "forum"
    branches.create(s, "Other")
    other = s.data.active_branch_id
    s.data.creative.style = "badge"
    branches.switch(s, next(b for b in s.data.branches if b != other))
    assert s.data.creative.style == "forum"
    recipe = recipes.capture(s, original.id)
    s.data.recipes = [recipe.model_dump()]
    file = tmp_path / "retro.badshop"
    project.save(s, file)
    loaded = project.open_project(file)
    assert loaded.data.creative == s.data.creative
    assert loaded.data.recipes == s.data.recipes
    assert loaded.data.steps[0].params == original.params
    old = json.loads(s.data.model_dump_json(by_alias=True))
    old["schema"] = 2
    old.pop("creative")
    old.pop("recipes")
    assert project._session_data(file, json.dumps(old).encode()).creative.style == "geocities"


def test_recipes_preserve_outputs_on_cancellation_and_reject_network():
    s = Session.new()
    a = imported(s)
    b = imported(s, "blue")
    event = threading.Event()
    recipe = recipes.Recipe(
        name="badge",
        steps=[{"tool": "export_profile", "params": {"image": "$input", "profile": "web-button"}}],
    )
    s.on_change = lambda: event.set() if any(step.status == "done" for step in s.data.steps) else None
    result = recipes.run(s, recipe, [a, b], event)
    assert result["cancelled"] and len(result["completed"]) == 1
    assert s.data.steps[0].outputs
    with pytest.raises((ValidationError, EngineError)):
        recipes.Recipe(name="remote", steps=[{"tool": "fetch", "params": {"query": "cat"}}])


def test_credit_ancestry_includes_both_composition_inputs():
    s = Session.new()
    a = imported(s, source=Source(kind="one", license="CC0"))
    b = imported(s, "blue", source=Source(kind="two", creator="Artist"))
    step = s.run_tool("retro_layout", {"style": "forum", "title": "TEST", "images": [a, b]}, "user")
    assert {r["kind"] for r in recipes.credits(s, step.outputs[0])["sources"]} == {"one", "two"}


def test_recipe_maps_scalar_and_list_inputs_without_rewriting_the_recipe():
    session = Session.new()
    source = imported(session, "red")
    recipe = recipes.Recipe(name="blink", steps=[
        {"tool": "filter", "params": {"image": "$input", "names": ["invert"]}},
        {"tool": "animate", "params": {"images": ["$input", "$step0"], "delay": 100}},
    ])
    before = recipe.model_dump()
    result = recipes.run(session, recipe, [source], threading.Event())
    assert not result["errors"] and not result["cancelled"]
    first, second = session.data.steps
    assert first.params["image"] == source
    assert second.params["images"] == [source, first.outputs[0]]
    assert recipe.model_dump() == before
    with Image.open(io.BytesIO(session.artifacts.data(second.outputs[0]))) as image:
        assert image.n_frames == 2
        assert image.convert("RGB").getpixel((0, 0)) == (255, 0, 0)
        image.seek(1)
        assert image.convert("RGB").getpixel((0, 0)) == (0, 255, 255)


def test_offline_rejects_even_trusted_url_before_request(monkeypatch):
    monkeypatch.setattr(
        netpolicy, "refuse_private", lambda *a, **k: pytest.fail("must not resolve DNS offline")
    )
    with netpolicy.guarded(frozenset({"https://example.com/image.png"}), True):
        with pytest.raises(EngineError, match="disabled"):
            assets.URL_POLICY("https://example.com/image.png")
    call = execute_call(
        ToolCall("collection_items", {"kind": "lospec", "identifier": "pico-8"}, {}, "test", no_remote=True)
    )
    assert not call.ok and not call.crashed and "disabled" in call.error_message


def test_iiif_v3_and_archive_preserve_rights_and_pagination(monkeypatch):
    monkeypatch.setattr(
        discovery,
        "_json",
        lambda *a, **k: {
            "rights": "https://creativecommons.org/publicdomain/zero/1.0/",
            "requiredStatement": {"value": {"en": ["Museum"]}},
            "items": [
                {
                    "label": {"en": ["Page 1"]},
                    "items": [
                        {
                            "items": [
                                {
                                    "motivation": "painting",
                                    "body": {"type": "Image", "id": "https://example.com/page.jpg"},
                                }
                            ]
                        }
                    ],
                }
            ],
        },
    )
    data = collections.browse(
        collections.CollectionParams(kind="iiif", identifier="https://example.com/manifest")
    ).data
    assert data["candidates"][0]["source"]["creator"] == "Museum"
    assert data["candidates"][0]["source"]["license"].endswith("/zero/1.0/")
    monkeypatch.setattr(
        discovery,
        "_json",
        lambda *a, **k: {
            "metadata": {"creator": "Archive artist"},
            "files": [{"name": "a b.png"}, {"name": "c.jpg"}, {"name": "script.exe"}],
        },
    )
    data = collections.browse(collections.CollectionParams(kind="archive", identifier="test", limit=1)).data
    assert data["next_offset"] == 1 and data["total"] == 2
    assert data["candidates"][0]["url"].endswith("a%20b.png")
    assert data["candidates"][0]["source"]["license"] is None


def test_stock_cache_and_credits_never_contain_credentials(tmp_path, monkeypatch):
    from badshop.engine import stock_sources

    monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BADSHOP_PIXABAY_API_KEY", "private-test-secret")
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return json.dumps(
            {
                "hits": [
                    {
                        "largeImageURL": "https://example.org/photo.png",
                        "previewURL": "https://example.org/thumb.png",
                        "pageURL": "https://example.org/photo",
                        "user": "Photographer",
                        "tags": "cat",
                    }
                ]
            }
        ).encode(), "application/json"

    monkeypatch.setattr(assets, "http_get", get)
    first = stock_sources.search("pixabay", "cat", 3)
    assert stock_sources.search("pixabay", "cat", 3) == first and len(calls) == 1
    assert first[0]["source"]["creator"] == "Photographer"
    assert "private-test-secret" not in json.dumps(first)
    assert "private-test-secret" not in next((tmp_path / "source-previews").glob("*.json")).read_text()


def test_source_keychain_uses_index_without_storing_secret(tmp_path, monkeypatch):
    import keyring
    from badshop.engine import source_keys

    monkeypatch.setenv("BADSHOP_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("BADSHOP_PEXELS_API_KEY", raising=False)
    stored = {}
    monkeypatch.setattr(
        keyring, "set_password", lambda service, name, key: stored.update({(service, name): key})
    )
    monkeypatch.setattr(keyring, "get_password", lambda service, name: stored.get((service, name)))
    monkeypatch.setattr(keyring, "delete_password", lambda service, name: stored.pop((service, name)))
    source_keys.set_key("pexels", "secret-value")
    assert source_keys.configured("BADSHOP_PEXELS_API_KEY")
    assert source_keys.resolve("BADSHOP_PEXELS_API_KEY") == "secret-value"
    assert "secret-value" not in (tmp_path / "source-keys.json").read_text()
    source_keys.set_key("pexels", "")
    assert not source_keys.configured("BADSHOP_PEXELS_API_KEY")


def test_authorization_is_removed_on_cross_origin_redirect():
    import urllib.request

    request = urllib.request.Request(
        "https://api.example.com/image",
        headers={"Authorization": "private", "X-Subscription-Token": "private"},
    )
    redirect = assets._WebOnlyRedirects().redirect_request(
        request, io.BytesIO(), 302, "found", {}, "https://other.example.com/image"
    )
    assert not redirect.has_header("Authorization") and not redirect.has_header("X-subscription-token")


def test_lospec_empty_author_is_valid_metadata(monkeypatch):
    monkeypatch.setattr(discovery, '_json', lambda *a, **k: {'name': 'PICO-8', 'author': '', 'colors': ['000000', 'ffffff']})
    result = collections.browse(collections.CollectionParams(kind='lospec', identifier='pico-8'))
    assert result.data['author'] == ''
    assert result.data['colors'] == ['#000000', '#ffffff']
def test_png_export_profile_keeps_hard_transparency():
    from badshop.engine.retro import ExportProfileParams, export_profile
    from PIL import Image
    image = Image.new("RGBA", (2, 2), (200, 10, 20, 0))
    image.putpixel((1, 1), (10, 220, 30, 255))
    output = export_profile(ExportProfileParams(image="test", profile="avatar", format="PNG"), image).outputs[0]
    assert output.image.mode == "RGBA"
    assert output.image.getpixel((0, 0))[3] == 0
    assert output.image.getpixel((output.image.width - 1, output.image.height - 1)) == (10, 220, 30, 255)
