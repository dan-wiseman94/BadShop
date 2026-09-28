"""User settings (spec 8.5, 9): one JSON file in the config dir. Keys and secrets never go in it."""

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

import platformdirs
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from badshop.engine.errors import EngineError

ApprovalMode = Literal["auto", "ask_changes", "ask_all"]
FILE = "settings.json"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    approval_mode: ApprovalMode = "ask_changes"  # the mode new sessions start in
    auto_replay: bool = True  # replay the later steps as soon as the user edits one
    output_dir: str | None = None  # None: files.default_output_dir()
    step_budget: int = Field(40, ge=1, le=500)  # tool calls per agent turn
    tool_timeout_s: float = Field(120.0, ge=1, le=3600)  # wall clock per tool call
    tool_memory_mb: int = Field(3072, ge=256, le=65536)  # memory per tool call
    fake_provider_script: str | None = None  # a ScriptedProvider JSON file (tests and demos, until Plan 3)

    @field_validator("output_dir")
    @classmethod
    def _absolute(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            folder = Path(v).expanduser()
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
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=FILE + ".", suffix=".part")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(s.model_dump_json(indent=2) + "\n")
        os.replace(tmp, path)
    except OSError as e:
        if tmp:
            Path(tmp).unlink(missing_ok=True)
        raise EngineError(f"can't save the settings ({e})",
                          hint=f"check that {path.parent} is writable") from None
