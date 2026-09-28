"""The session data model (spec §6). It is also session.json in a .badshop project file."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from badshop.engine.result import EXT as OUTPUT_EXT

SCHEMA = 1  # session.json's "schema"; bump it (and migrate older files) whenever the saved shape changes

ImageFormat = Literal["PNG", "JPEG", "GIF", "WEBP", "BMP", "TIFF"]
EXT: dict[str, str] = {**OUTPUT_EXT, "BMP": ".bmp", "TIFF": ".tiff"}  # tool outputs keep their CLI extensions

StepStatus = Literal["proposed", "approved", "running", "done", "error", "rejected", "stale"]


class Source(BaseModel):
    """Where a fetched or imported image came from (EngineResult.data["sources"] entries)."""

    model_config = ConfigDict(frozen=True)
    kind: str  # commons | openverse | wikipedia | imgflip | twemoji | url | clipboard
    url: str | None = None  # the URL that delivered the bytes
    page: str | None = None  # the page describing the image (licence, author)
    title: str | None = None
    license: str | None = None
    creator: str | None = None


class ArtifactMeta(BaseModel):
    """An immutable image. Frozen: an artifact produced twice keeps its first label and produced_by."""

    model_config = ConfigDict(frozen=True)
    id: str = Field(pattern=r"^[0-9a-f]{64}$")  # sha256 of the stored bytes
    label: str
    width: int
    height: int
    format: ImageFormat
    mime: str
    frames: int = 1
    produced_by: str | None = None  # step id
    source: Source | None = None
    original_id: str | None = None  # an import's working copy -> the full-size original it was made from

    @property
    def ext(self) -> str:
        return EXT[self.format]


class StepError(BaseModel):
    message: str
    hint: str | None = None


class Step(BaseModel):
    id: str  # "s1", "s2", ...
    index: int
    tool: str
    params: dict  # validated, JSON-safe; image refs are full artifact ids
    actor: str  # "user" | "agent:<provider>" | "cli:<claude|codex|gemini>"
    status: StepStatus
    outputs: list[str] = []
    result_text: str = ""
    data: dict | None = None
    error: StepError | None = None
    reason: str | None = None  # why the actor proposed it (shown with the approval)
    edited: bool = False
    started_at: float | None = None
    finished_at: float | None = None
    cache_key: str | None = None
    # Only on a step where a replay stopped (status "error"): the outputs of its last good run, which the
    # stale steps after it still reference. The next replay that gets past it maps them to its new
    # outputs; it is saved with the session, so reopening a project in between loses nothing.
    previous_outputs: list[str] = []


class Part(BaseModel):
    type: Literal["text", "image"]
    text: str | None = None
    artifact_id: str | None = None


class Message(BaseModel):
    id: str  # "m1", "m2", ...
    role: Literal["user", "assistant", "system_note"]
    content: list[Part]
    step_ids: list[str] = []


class SessionData(BaseModel):
    """The whole session. `schema` would shadow BaseModel.schema, so the field is `schema_` with the alias
    "schema": always dump with `by_alias=True` (session.json says "schema": 1)."""

    model_config = ConfigDict(populate_by_name=True)
    schema_: int = Field(SCHEMA, alias="schema")
    id: str
    name: str
    created_at: float
    provider_profile_id: str | None = None  # a profile id only: keys never go in the file
    approval_mode: Literal["auto", "ask_changes", "ask_all"] = "ask_changes"
    messages: list[Message] = []
    steps: list[Step] = []
    artifacts: dict[str, ArtifactMeta] = {}
    transcript: list[dict] = []  # the provider-format message history the agent resumes from
