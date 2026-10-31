"""What the agent loop needs from a model: one streamed completion in the OpenAI chat format.

Messages and tool definitions are OpenAI chat dicts (what LiteLLM takes, Plan 3). A provider streams its
text through `on_delta` as it arrives and returns the whole reply; a failed call raises ProviderError."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict | str  # a str when the model sent JSON that doesn't parse


@dataclass
class Reply:
    text: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)


class ProviderError(Exception):
    """The model call failed (auth, rate limit, context too long, network). The turn ends with its message."""


class Provider(Protocol):
    actor: str  # the actor its steps are recorded under: "agent:<provider>", e.g. "agent:fake"

    async def complete(self, messages: list[dict], tools: list[dict],
                       on_delta: Callable[[str], None]) -> Reply: ...
