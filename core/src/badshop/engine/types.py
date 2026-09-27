"""Parameter types shared by every tool. The JSON-schema `format` drives UI widgets and CLI nargs."""

from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field

# Far off-canvas is fine (it clamps or misses); past this a coordinate is a typo, and C-level drawing overflows.
Coord = Annotated[int, Field(ge=-100_000, le=100_000)]

ImageRef = Annotated[str, Field(max_length=4096, json_schema_extra={"format": "badshop-image"})]
Point = Annotated[tuple[Coord, Coord], Field(json_schema_extra={"format": "badshop-point"})]
Box = Annotated[tuple[Coord, Coord, Coord, Coord], Field(json_schema_extra={"format": "badshop-box"})]
Spot = Annotated[tuple[Coord, Coord, Coord], Field(json_schema_extra={"format": "badshop-spot"})]  # x, y, radius
Color = Annotated[str, Field(max_length=100, json_schema_extra={"format": "color"})]  # Pillow refuses longer


class Params(BaseModel):
    """Base for every tool's parameters. ClassVars are CLI metadata and never appear in the schema.

    Unknown fields and non-finite numbers (inf, nan) are refused: every caller, a model included, gets a
    clean "bad parameters" error instead of a crash deep in Pillow or OpenCV."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    POSITIONAL: ClassVar[tuple[str, ...]] = ()  # fields that are positional on the CLI, in order
    FLAGS: ClassVar[dict[str, str]] = {}  # field -> CLI flag, when not --field-name
