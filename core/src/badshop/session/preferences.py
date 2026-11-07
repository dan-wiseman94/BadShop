"""Portable creative choices; credentials and machine paths never enter projects."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreativePreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style: str = "geocities"
    density: Literal["sparse", "balanced", "chaotic"] = "balanced"
    era_strictness: Literal["inspired", "strict", "mashup"] = "inspired"
    exact_text: bool = True
    seed: int = 1
    fit: Literal["contain", "cover", "stretch"] = "contain"
    takes: int = Field(1, ge=1, le=6)
    remember_history: bool = True
    animation_delay: int = Field(100, ge=20, le=2000)
    export_profile: Literal["web-button", "blinkie", "forum-signature", "avatar", "wallpaper", "original"] = (
        "original"
    )
    favorite_styles: list[str] = Field(default_factory=list, max_length=100)
    favorite_briefs: list[str] = Field(default_factory=list, max_length=50)
    saved_searches: list[str] = Field(default_factory=list, max_length=50)
    locks: dict[str, bool] = Field(default_factory=dict, max_length=12)
    mixer: dict[str, str] = Field(default_factory=dict, max_length=12)
    source_roles: dict[str, str] = Field(default_factory=dict, max_length=12)

    @field_validator("style")
    @classmethod
    def valid_style(cls, value):
        from badshop.engine.retro import STYLES

        if value not in STYLES:
            raise ValueError("unknown retro style")
        return value

    @field_validator("favorite_briefs", "saved_searches")
    @classmethod
    def bounded_strings(cls, value):
        if any(len(s) > 2000 for s in value):
            raise ValueError("saved text exceeds 2000 characters")
        return value

    @field_validator("mixer", "source_roles")
    @classmethod
    def bounded_values(cls, value):
        if any(len(k) > 50 or len(v) > 2000 for k, v in value.items()):
            raise ValueError("saved choice is too long")
        return value
