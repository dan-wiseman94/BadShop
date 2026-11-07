"""The tools API sessions build on (spec 5.2-5.4; carry-forward SP F15, SEC-S7, SEC-S8): validation apart
from execution, the one trusted actor, user-only fields and the two schemas, and the writes_files flag."""


import jsonschema
import pytest
from pydantic import Field

from badshop.engine import sources
from badshop.engine.errors import EngineError
from badshop.engine.result import EngineResult
from badshop.engine.types import ImageRef, Params
from badshop.tools import REGISTRY, registry, runner
from badshop.tools.registry import USER_ONLY, ToolSpec, llm_schema, ui_schema, user_only_fields
from conftest import FIXTURES
from memstore import MemoryStore

UNTRUSTED = ["agent:fake", "cli:claude", "cli:codex", "cli:gemini"]


# --- actors ---

def test_only_the_user_is_trusted():
    assert runner.is_trusted("user")
    for actor in [*UNTRUSTED, "", "User", "user ", "agent:user", "cli:user"]:
        assert not runner.is_trusted(actor), actor


# --- validate apart from execute (SP F15: the approval gate validates, lets the user edit, then runs) ---

def test_validate_returns_the_params_and_touches_no_store():
    params = runner.validate("prep", {"image": "never/loaded.png", "max": "500"})
    assert type(params) is REGISTRY["prep"].params
    assert params.image == "never/loaded.png" and params.max == 500


# --- user-only fields (SEC-S8: the clipboard is user input) ---


@pytest.mark.parametrize("actor", UNTRUSTED)
@pytest.mark.parametrize("value", [True, 1, "true", "yes"])
def test_a_model_cannot_read_the_clipboard(monkeypatch, actor, value):
    # A steered model could pull a password-manager screenshot, or a one-click login link, off the clipboard.
    monkeypatch.setattr(sources, "read_clipboard", lambda: pytest.fail("a model read the clipboard"))
    with pytest.raises(EngineError, match="^fetch: clipboard can only be set by the user$") as e:
        runner.run_tool("fetch", {"clipboard": value}, MemoryStore(), actor=actor)
    assert e.value.hint == "leave clipboard out, or ask the user to do it in the app"
    with pytest.raises(EngineError, match="^fetch: clipboard can only be set by the user$"):
        runner.validate("fetch", {"query": "cat", "clipboard": value}, actor)


@pytest.mark.parametrize("actor", UNTRUSTED)
def test_a_model_may_leave_the_clipboard_at_its_default(actor):
    for raw in ({"query": "cat"}, {"query": "cat", "clipboard": False}, {"query": "cat", "clipboard": "no"}):
        assert runner.validate("fetch", raw, actor).clipboard is False


def test_the_user_still_reads_the_clipboard(monkeypatch):
    monkeypatch.setattr(sources, "read_clipboard", lambda: ((FIXTURES / "lincoln.png").read_bytes(), None))
    run = runner.run_tool("fetch", {"clipboard": True}, MemoryStore(), actor="user")
    assert [o.key for o in run.result.outputs] == ["fetched"]


class _Secret(Params):
    image: ImageRef
    note: list[str] = Field(default_factory=list, json_schema_extra={USER_ONLY: True})
    path: str | None = Field(None, description="a file the user picks", json_schema_extra={USER_ONLY: True})
    size: int = 3


class _RequiredSecret(Params):
    image: ImageRef
    path: str = Field(json_schema_extra={USER_ONLY: True})


class _OnlySecret(Params):
    path: str = Field(json_schema_extra={USER_ONLY: True})


def _spec(name: str, params: type[Params]) -> ToolSpec:
    return ToolSpec(name=name, params=params, category="inspect", summary="test tool",
                    description="a tool that only exists in this test file",
                    run=lambda p, s: EngineResult(lines=[f"{p.note} {p.path} {p.size}"]))


def test_user_only_fields_bind_every_untrusted_actor(monkeypatch):
    monkeypatch.setitem(registry.REGISTRY, "_secret", _spec("_secret", _Secret))
    assert user_only_fields(_Secret) == {"note", "path"}
    raw = {"image": "a.png", "note": ["hi"], "path": "/home/me/p.png"}
    assert runner.run_tool("_secret", raw, MemoryStore()).result.lines == ["['hi'] /home/me/p.png 3"]
    for actor in UNTRUSTED:
        with pytest.raises(EngineError, match="^_secret: note can only be set by the user$"):
            runner.validate("_secret", raw, actor)  # the first user-only field, in declaration order
        with pytest.raises(EngineError, match="^_secret: path can only be set by the user$"):
            runner.validate("_secret", {"image": "a.png", "path": "/home/me/p.png"}, actor)
        # Defaults, a default_factory's included, are fine; so is everything that isn't user-only.
        plain = {"image": "a.png", "note": [], "path": None, "size": 9}
        assert runner.validate("_secret", plain, actor).size == 9


# --- the two schemas ---

def test_the_model_never_sees_the_clipboard():
    spec = REGISTRY["fetch"]
    ui, llm = ui_schema(spec), llm_schema(spec)
    assert ui == spec.params.model_json_schema()
    assert ui["properties"]["clipboard"][USER_ONLY] is True  # the UI knows the field is the user's own
    assert list(llm["properties"]) == ["query", "source", "n"]
    assert llm["additionalProperties"] is False  # a model that sends clipboard anyway is off its schema
    jsonschema.Draft202012Validator.check_schema(llm)
    jsonschema.Draft202012Validator(llm).validate({"query": "cat", "n": 2})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(llm).validate({"query": "cat", "clipboard": True})


def test_llm_schema_drops_user_only_fields_from_required():
    llm = llm_schema(_spec("_required", _RequiredSecret))
    assert ui_schema(_spec("_required", _RequiredSecret))["required"] == ["image", "path"]
    assert llm["required"] == ["image"] and list(llm["properties"]) == ["image"]
    only = llm_schema(_spec("_only", _OnlySecret))
    assert only["properties"] == {} and "required" not in only  # an empty `required` is left out
    for schema in (llm, only):
        jsonschema.Draft202012Validator.check_schema(schema)


def test_schemas_are_fresh_copies():
    # Callers decorate what they get (tool definitions, forms); that must never leak into the next call.
    spec = REGISTRY["fetch"]
    llm_schema(spec)["properties"]["query"]["description"] = "changed"
    ui_schema(spec)["properties"].clear()
    assert llm_schema(spec)["properties"]["query"]["description"].startswith("search words")
    assert "clipboard" in ui_schema(spec)["properties"]


# --- flags (SEC-S7: key the approval gate on read_only; export writes a file) ---


def test_read_only_tools_change_nothing():
    # "Ask for changes" runs read_only tools without asking (spec 7): none may add images, use the
    # network or write a file.
    read_only = [spec for spec in REGISTRY.values() if spec.read_only]
    assert sorted(spec.name for spec in read_only) == ["find", "info", "view"]
    for spec in read_only:
        assert not (spec.mutates or spec.network or spec.writes_files), spec.name
