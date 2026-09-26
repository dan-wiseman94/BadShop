"""Parameter types shared by every tool. The JSON-schema `format` drives UI widgets and CLI nargs."""

from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field

ImageRef = Annotated[str, Field(json_schema_extra={"format": "badshop-image"})]
Point = Annotated[tuple[int, int], Field(json_schema_extra={"format": "badshop-point"})]
Box = Annotated[tuple[int, int, int, int], Field(json_schema_extra={"format": "badshop-box"})]
Spot = Annotated[tuple[int, int, int], Field(json_schema_extra={"format": "badshop-spot"})]  # x, y, radius
Color = Annotated[str, Field(json_schema_extra={"format": "color"})]


class Params(BaseModel):
    """Base for every tool's parameters. ClassVars are CLI metadata and never appear in the schema."""

    model_config = ConfigDict(extra="forbid")
    POSITIONAL: ClassVar[tuple[str, ...]] = ()  # fields that are positional on the CLI, in order
    FLAGS: ClassVar[dict[str, str]] = {}  # field -> CLI flag, when not --field-name
