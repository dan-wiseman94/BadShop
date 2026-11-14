"""What the agent loop needs from a model: one streamed completion in the OpenAI chat format.

Messages and tool definitions are OpenAI chat dicts (what LiteLLM takes, Plan 3). A provider streams its
text through `on_delta` as it arrives and returns the whole reply; a failed call raises ProviderError."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict | str  # a str when the model sent JSON that doesn't parse
    thought_signature: str | None = None  # opaque continuation data from Responses APIs


@dataclass
class Reply:
    text: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None
    actual_model: str | None = None


ErrorCategory = Literal['unknown', 'authentication', 'permission', 'unavailable', 'rate_limit', 'context', 'timeout', 'connection', 'request']


class ProviderError(Exception):
    """Safe advice with adapter-classified failure and explicit continuation policy."""

    def __init__(self, message: str, *, category: ErrorCategory = 'unknown', retryable: bool = True):
        super().__init__(message)
        self.category, self.retryable = category, retryable


@dataclass(frozen=True)
class ContextPolicy:
    full_image_ids: bool = False
    continuation_metadata: bool = False


class Provider(Protocol):
    # Concrete adapters inherit these explicit safe defaults. Projection policy
    # is independent of remote model capability discovery or authorization.
    context_policy = ContextPolicy()
    model: str | None = None

    actor: str  # the actor its steps are recorded under: "agent:<provider>", e.g. "agent:fake"

    async def complete(self, messages: list[dict], tools: list[dict],
                       on_delta: Callable[[str], None]) -> Reply: ...
