"""The session data model (spec §6). It is also session.json in a .badshop project file."""

from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from badshop.engine.result import EXT as OUTPUT_EXT
from badshop.session.preferences import CreativePreferences

SCHEMA = 6  # logical artifact uses and stable invocation/output bindings

ImageFormat = Literal["PNG", "JPEG", "GIF", "WEBP", "BMP", "TIFF", "AVIF", "HEIF"]
EXT: dict[str, str] = {**OUTPUT_EXT, "BMP": ".bmp", "TIFF": ".tiff", "AVIF": ".avif", "HEIF": ".heic"}  # tool outputs keep their CLI extensions

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
    """An immutable image use with independent provenance and shared encoded bytes."""

    model_config = ConfigDict(frozen=True)
    id: str = Field(pattern=r"^[0-9a-f]{64}$")  # logical use, independent of byte identity
    blob_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    invocation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    output_key: str | None = None
    inputs: tuple[str, ...] = ()
    legacy_identity: bool = False
    label: str
    width: int
    height: int
    format: ImageFormat
    mime: str
    frames: int = 1
    produced_by: str | None = None  # step id
    source: Source | None = None
    original_id: str | None = None  # an import's working copy -> the full-size original it was made from

    @model_validator(mode='before')
    @classmethod
    def legacy_blob(cls, value):
        if isinstance(value, dict) and 'blob_id' not in value:
            value = {**value, 'blob_id': value.get('id'), 'legacy_identity': True}
        return value

    @field_validator('inputs', mode='before')
    @classmethod
    def immutable_inputs(cls, value):
        # The legacy model validator crosses the JSON/Python validation boundary.
        # Restore the immutable representation without relaxing element validation.
        return tuple(value) if isinstance(value, list) else value

    @property
    def ext(self) -> str:
        return EXT[self.format]


class StepError(BaseModel):
    message: str
    hint: str | None = None


class Step(BaseModel):
    id: str  # "s1", "s2", ...
    invocation_id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r"^[0-9a-f]{32}$")
    operation_id: str | None = Field(None, pattern=r"^[0-9a-f]{32}$")
    batch_row: int | None = Field(None, ge=0)
    batch_item: int | None = Field(None, ge=0)
    output_ports: dict[str, str] = {}
    # Parameter references bind to a producer and port, not to byte equality.
    input_bindings: dict[str, tuple[str, str]] = {}
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
    locked_fields: list[str] = Field(default_factory=list, max_length=30)
    bypassed: bool = False
    lock_review: bool = False
    lock_approved: bool = False


class Part(BaseModel):
    type: Literal["text", "image"]
    text: str | None = None
    artifact_id: str | None = None


class Message(BaseModel):
    id: str  # "m1", "m2", ...
    role: Literal["user", "assistant", "system_note"]
    content: list[Part]
    step_ids: list[str] = []


class BranchSnapshot(BaseModel):
    """One independent creative direction; immutable image bytes remain shared by the project."""

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    name: str = Field(min_length=1, max_length=200)
    created_at: float
    automatic: bool = False  # legacy/unmarked directions are retained conservatively
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_step_number: int = Field(default=0, ge=0)
    max_message_number: int = Field(default=0, ge=0)
    artifact_ids: list[str] = []
    creative: CreativePreferences = Field(default_factory=CreativePreferences)


class HistoryState(BaseModel):
    steps: list[Step] = []
    messages: list[Message] = []
    transcript: list[dict] = []


class SessionData(BaseModel):
    """The whole session. `schema` would shadow BaseModel.schema, so the field is `schema_` with the alias
    "schema": always dump with `by_alias=True` (session.json says "schema": 2)."""

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
    transcript: list[dict] = []  # the canonical conversation history the agent resumes from
    active_branch_id: str | None = None
    branches: dict[str, BranchSnapshot] = {}
    history_nodes: dict[str, str] = {}
    creative: CreativePreferences = Field(default_factory=CreativePreferences)
    recipes: list[dict] = Field(default_factory=list,max_length=50)
    undo_branch_id: str | None = None
    manual_undo: list[BranchSnapshot] = Field(default_factory=list, max_length=30)
    manual_redo: list[BranchSnapshot] = Field(default_factory=list, max_length=30)
    pause_before_finish: bool = False

    @field_validator('recipes')
    @classmethod
    def valid_recipes(cls, value):
        from badshop.session.recipes import Recipe
        return [Recipe.model_validate(row).model_dump(mode='json') for row in value]

    def branch_state(self, branch: BranchSnapshot) -> HistoryState:
        from badshop.session.history import materialize
        return HistoryState.model_validate(materialize(self.history_nodes, branch.revision))

    def set_branch_state(self, branch: BranchSnapshot, state: HistoryState) -> None:
        from badshop.session.history import capture
        branch.revision = capture(self.history_nodes, state.model_dump(mode='json'))

    def collect_history(self) -> None:
        from badshop.session.history import collect
        collect(self.history_nodes, [branch.revision for branch in
                [*self.branches.values(), *self.manual_undo, *self.manual_redo]] + list(self._history_leases))

    _history_leases: list[str] = PrivateAttr(default_factory=list)
