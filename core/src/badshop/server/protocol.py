"""Wire ownership contracts; these identities are not persisted project metadata."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = 1
CLI_METHODS = frozenset({'tools.list', 'tools.run', 'artifacts.get'})
GLOBAL_EVENTS = frozenset({'asset.progress', 'provider.status', 'updates.cancel', 'core.log'})


class DocumentContext(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    core_instance_id: str
    document_id: str
    document_incarnation: str
    branch_id: str | None
    revision: int = Field(ge=0)
    event_seq: int = Field(ge=0)


class Welcome(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    type: Literal['welcome'] = 'welcome'
    actor: str
    version: str
    protocol: Literal[1] = PROTOCOL_VERSION
    build_id: str
    core_instance_id: str
    event_seq: int = Field(ge=0)
    capabilities: list[str]
    context: DocumentContext | None = None
