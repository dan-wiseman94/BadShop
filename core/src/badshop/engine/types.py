"""Parameter types shared by every tool. The JSON-schema `format` drives UI widgets and CLI nargs."""

import re
from typing import Annotated, ClassVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

_NOT_IN_NAMES = re.compile(r"[/\\:\x00-\x1f\x7f-\x9f]")  # folders, drives, control characters


def _plain_name(v: str) -> str:
    if not v.strip(" .") or _NOT_IN_NAMES.search(v):
        raise ValueError("give a plain file name with no folders, e.g. lincoln_lasers")
    return v


# A finished file's name (no extension): it always lands inside the output folder, whoever picks it.
FileName = Annotated[str, AfterValidator(_plain_name), Field(max_length=100)]

# Far off-canvas is fine (it clamps or misses); past this a coordinate is a typo, and C-level drawing overflows.
Coord = Annotated[int, Field(ge=-100_000, le=100_000)]

_AXES = "pixels of the image being edited: (0, 0) is its top-left corner, x grows rightward and y grows downward."


def _coordinates(fmt: str, convention: str):
    """Schema hook for a coordinate type: its format, and the convention appended to whatever the field
    says, so every schema (a plain field, an Optional one, list items) tells a model where (0, 0) is."""
    def extra(schema: dict) -> None:
        schema["format"] = fmt
        schema["description"] = f"{schema['description']}. {convention}" if schema.get("description") else convention
    return extra


ImageRef = Annotated[str, Field(max_length=4096, json_schema_extra={"format": "badshop-image"})]
Point = Annotated[tuple[Coord, Coord], Field(json_schema_extra=_coordinates(
    "badshop-point", f"X Y in {_AXES}"))]
Box = Annotated[tuple[Coord, Coord, Coord, Coord], Field(json_schema_extra=_coordinates(
    "badshop-box", f"X1 Y1 X2 Y2 in {_AXES}"))]
Spot = Annotated[tuple[Coord, Coord, Coord], Field(json_schema_extra=_coordinates(
    "badshop-spot", f"X Y R, a centre and a radius, in {_AXES}"))]
Color = Annotated[str, Field(max_length=100, json_schema_extra={"format": "color"})]  # Pillow refuses longer
Seed = Annotated[int, Field(json_schema_extra={"format": "badshop-seed"})]  # same seed, same pixels: a reroll knob


class Params(BaseModel):
    """Base for every tool's parameters. ClassVars are CLI metadata and never appear in the schema.

    Unknown fields and non-finite numbers (inf, nan) are refused: every caller, a model included, gets a
    clean "bad parameters" error instead of a crash deep in Pillow or OpenCV."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    POSITIONAL: ClassVar[tuple[str, ...]] = ()  # fields that are positional on the CLI, in order
    FLAGS: ClassVar[dict[str, str]] = {}  # field -> CLI flag, when not --field-name
