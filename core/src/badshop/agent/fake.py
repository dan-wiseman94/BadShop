"""A scripted stand-in for a model. The agent tests, the server's end-to-end test and the UI's
Playwright suite drive real turns with it: offline, fast and the same every time."""

import asyncio
import copy
import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from badshop.agent.provider import ProviderError, Reply, ToolCallRequest
from badshop.engine.errors import EngineError
from badshop.tools.runner import explain

END_OF_SCRIPT = "(end of script)"
CHUNK = 12  # characters per streamed delta
SCRIPT_HINT = ('the file must be a JSON list like [{"text": "...", "tool_calls": [{"name": "find", '
               '"arguments": {"image": "a3f9c1d2"}}]}]')


class _ScriptCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    arguments: dict | str = Field(default_factory=dict)


class _ScriptReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = ""
    tool_calls: list[_ScriptCall] = []
    error: str | None = None  # the provider fails with this message instead of replying


class ScriptedProvider:
    """Plays `replies` in order, one per completion. A ProviderError in the list is raised at its turn."""

    actor = "agent:fake"

    def __init__(self, replies: list[Reply | ProviderError]):
        self.replies = list(replies)
        self.received: list[list[dict]] = []  # the messages of every completion, as they were sent
        self._next = 0

    @classmethod
    def from_file(cls, path: Path | str) -> "ScriptedProvider":
        """A JSON list of {"text", "tool_calls": [{"name", "arguments"}]} (or {"error": "..."}) entries.
        Tool call ids are generated in order across the whole script: call_1, call_2, ..."""
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError) as e:  # bad JSON or not UTF-8, or nested too deep
            raise EngineError(f"can't read the fake provider script {path} ({e})", hint=SCRIPT_HINT) from None
        try:
            entries = TypeAdapter(list[_ScriptReply]).validate_python(raw)
        except ValidationError as e:
            raise EngineError(f"the fake provider script {path} is not valid", hint=explain(e)) from None
        replies: list[Reply | ProviderError] = []
        n = 0
        for entry in entries:
            if entry.error is not None:
                replies.append(ProviderError(entry.error))
                continue
            calls = []
            for c in entry.tool_calls:
                n += 1
                calls.append(ToolCallRequest(id=f"call_{n}", name=c.name, arguments=c.arguments))
            replies.append(Reply(text=entry.text, tool_calls=calls))
        return cls(replies)

    async def complete(self, messages: list[dict], tools: list[dict],
                       on_delta: Callable[[str], None]) -> Reply:
        self.received.append(copy.deepcopy(messages))
        if self._next < len(self.replies):
            reply = self.replies[self._next]
            self._next += 1
        else:
            reply = Reply(text=END_OF_SCRIPT)
        if isinstance(reply, ProviderError):
            raise reply
        for i in range(0, len(reply.text), CHUNK):
            await asyncio.sleep(0)  # a real stream waits on the network between chunks: Stop can land here
            on_delta(reply.text[i:i + CHUNK])
        return copy.deepcopy(reply)
