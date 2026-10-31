"""Provider profiles on disk; credentials live in the OS keychain or the environment."""

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator, model_validator

from badshop.engine.errors import EngineError
from badshop.server.settings import config_dir

SERVICE = "badshop.providers"


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    kind: Literal["api", "local", "openai_compatible", "cli"] = "api"
    label: str = Field(min_length=1, max_length=200)
    model: str = Field(default="", max_length=200)
    cli: Literal["claude", "codex", "gemini"] | None = None
    executable: str | None = None
    api_base: str | None = None
    api_key_ref: str | None = None
    api_key_env: str | None = Field(None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    capability_overrides: dict[Literal["vision", "tool_calls"], bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def provider_kind(self):
        if self.kind == "cli":
            if not self.cli:
                raise ValueError("CLI profiles require a CLI name")
            if self.api_base or self.api_key_ref or self.api_key_env:
                raise ValueError("CLI profiles use the CLI's own subscription login")
        elif not self.model.strip() or self.cli or self.executable:
            raise ValueError("API profiles require a model; CLI settings require kind=cli")
        if self.executable and not Path(self.executable).expanduser().is_absolute():
            raise ValueError("choose an absolute executable path")
        return self

    @field_validator("api_base")
    @classmethod
    def base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            url = urlsplit(value)
            valid = (url.scheme in ("http", "https") and url.hostname and not url.username
                     and not url.password and not url.query and not url.fragment)
            url.port  # validate the port too
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("use an http(s) base URL without credentials, query or fragment")
        return value.rstrip("/")


def profiles_path() -> Path:
    return config_dir() / "providers.json"


def load_profiles() -> dict[str, Profile]:
    path = profiles_path()
    if not path.exists():
        return {}
    try:
        profiles = TypeAdapter(list[Profile]).validate_json(path.read_bytes())
        if len({p.id for p in profiles}) != len(profiles):
            raise ValueError("duplicate ids")
        if any(p.api_key_ref is not None and p.api_key_ref != p.id
               and not p.api_key_ref.startswith(p.id + ":") for p in profiles):
            raise ValueError("foreign key reference")
        return {p.id: p for p in profiles}
    except (OSError, ValueError, RecursionError):
        raise EngineError("can't read the provider profiles", hint=f"check {path}") from None


def save_profiles(profiles: dict[str, Profile]) -> None:
    path = profiles_path()
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="providers.", suffix=".part")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump([p.model_dump(mode="json") for p in profiles.values()], fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except OSError:
        if tmp:
            Path(tmp).unlink(missing_ok=True)
        raise EngineError("can't save provider profiles", hint=f"check that {path.parent} is writable") from None


def _keyring():
    import keyring
    return keyring


def _keyring_error() -> EngineError:
    return EngineError("the OS keychain is unavailable or locked",
                       hint="unlock your keychain, or use api_key_env with an environment variable")


def store_key(profile_id: str, key: str) -> None:
    try:
        _keyring().set_password(SERVICE, profile_id, key)
    except Exception:
        raise _keyring_error() from None


def delete_key(profile_id: str) -> None:
    try:
        kr = _keyring()
        if kr.get_password(SERVICE, profile_id) is not None:
            kr.delete_password(SERVICE, profile_id)
    except Exception:
        raise _keyring_error() from None


def resolve_key(profile: Profile) -> str | None:
    if profile.api_key_env:
        key = os.environ.get(profile.api_key_env)
        if not key:
            raise EngineError(f"environment variable {profile.api_key_env} is not set",
                              hint="set it before starting badshop")
        return key
    if profile.api_key_ref:
        try:
            key = _keyring().get_password(SERVICE, profile.api_key_ref)
        except Exception:
            raise _keyring_error() from None
        if not key:
            raise EngineError("the provider key is missing from the keychain", hint="save the API key again")
        return key
    return None  # provider SDK environment defaults, or an unauthenticated local server


def parse_profile(raw: dict) -> Profile:
    try:
        return Profile.model_validate(raw)
    except ValidationError:
        # Validation input can contain a misplaced key: never echo it to an RPC response/log.
        raise EngineError("invalid provider profile", hint="check the model, label, URL and capability overrides") from None
