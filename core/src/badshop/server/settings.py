"""User settings (spec 8.5, 9): one JSON file in the config dir. Keys and secrets never go in it."""

import json
import os
from pathlib import Path
from typing import Literal

import platformdirs
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from badshop.files import expand_user_path
from badshop.atomic import write_text
from badshop.engine.errors import EngineError
from badshop.session.preferences import CreativePreferences

ApprovalMode = Literal["auto", "ask_changes", "ask_all"]
FILE = "settings.json"


class ExportPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    params: dict

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("give the export preset a name")
        return value.strip()

    @field_validator("params")
    @classmethod
    def export_params(cls, value):
        from badshop.engine.retro import ExportProfileParams
        if "image" in value:
            raise ValueError("export presets cannot reference a project image")
        return ExportProfileParams.model_validate({**value, "image": "preset"}).model_dump(exclude={"image"})


class RecentProject(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    path: str = Field(min_length=1, max_length=4096)
    name: str = Field(min_length=1, max_length=200)
    opened_at: float = Field(ge=0)
    thumbnail: str | None = Field(None, max_length=100000, pattern=r"^[A-Za-z0-9+/]*={0,2}$")


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    approval_mode: ApprovalMode = "ask_changes"  # the mode new sessions start in
    auto_replay: bool = True  # replay the later steps as soon as the user edits one
    output_dir: str | None = None  # None: files.default_output_dir()
    step_budget: int = Field(40, ge=1, le=500)  # tool calls per agent turn
    tool_timeout_s: float = Field(120.0, ge=1, le=3600)  # wall clock per tool call
    tool_memory_mb: int = Field(3072, ge=256, le=65536)  # memory per tool call
    fake_provider_script: str | None = None  # a ScriptedProvider JSON file (tests and demos, until Plan 3)
    creative_defaults: CreativePreferences = Field(default_factory=CreativePreferences)
    export_presets: list[ExportPreset] = Field(default_factory=list, max_length=30)
    recent_projects: list[RecentProject] = Field(default_factory=list, max_length=20)
    saved_designs: list[dict] = Field(default_factory=list, max_length=50)
    no_remote: bool = False
    remember_history: bool = True
    source_allowlist: list[str] = Field(default_factory=list, max_length=40)
    rights_filter: Literal['any','known','public-domain'] = 'any'
    source_orientation: Literal['any','landscape','portrait','square'] = 'any'

    @field_validator("saved_designs")
    @classmethod
    def portable_designs(cls, value):
        from badshop.session.recipes import Recipe
        try:
            return [Recipe.model_validate(item).model_dump(mode="json") for item in value]
        except EngineError as error:
            raise ValueError(error.message) from error

    @field_validator('source_allowlist')
    @classmethod
    def source_ids(cls, value):
        from badshop.engine.discovery import SOURCE_CONFIG
        if any(s not in SOURCE_CONFIG for s in value):
            raise ValueError('unknown image source')
        return list(dict.fromkeys(value))

    @field_validator("output_dir")
    @classmethod
    def _absolute(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            folder = expand_user_path(v)
        except RuntimeError:  # "~name/..." for a user this computer doesn't have: no home folder to expand
            raise ValueError("give an absolute folder path (that home folder doesn't exist)") from None
        if not folder.is_absolute():
            raise ValueError("give an absolute folder path")
        return v


def config_dir() -> Path:
    env = os.environ.get("BADSHOP_CONFIG_DIR")
    return Path(env) if env else Path(platformdirs.user_config_dir("badshop", appauthor=False))


def settings_path() -> Path:
    return config_dir() / FILE


def load_settings() -> Settings:
    """The saved settings. A missing or unreadable file gives the defaults; a value that is no longer
    valid (or a key this version doesn't know) is dropped, so a bad file never stops the core."""
    try:
        raw = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):  # RecursionError: nested deeper than json's scanner goes
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    values = {k: v for k, v in raw.items() if k in Settings.model_fields}
    try:
        return Settings.model_validate(values)
    except ValidationError as e:
        bad = {err["loc"][0] for err in e.errors() if err["loc"]}
        return Settings.model_validate({k: v for k, v in values.items() if k not in bad})


def save_settings(s: Settings) -> None:
    """Write the settings atomically: a temp file in the same folder, then os.replace."""
    path = settings_path()
    try:
        write_text(path, s.model_dump_json(indent=2) + "\n")
    except OSError as e:
        raise EngineError(f"can't save the settings ({e})",
                          hint=f"check that {path.parent} is writable") from None
