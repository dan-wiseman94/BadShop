"""Provider-neutral conversation records and bounded, disposable request projection.

The document stores named calls and text, never provider message envelopes or
image payloads. OpenAI-shaped dictionaries exist only at the provider boundary.
Legacy schema 1–5 calls are accepted by the archive migration adapter.
"""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from badshop.engine.errors import EngineError

MAX_CONTEXT_BYTES = 128 * 1024
MAX_CONTEXT_TURNS = 20


class ConversationCall(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(min_length=1, max_length=1024)
    name: str = Field(min_length=1, max_length=128)
    arguments: str
    provider_metadata: dict[str, str] = {}


class CompletionInfo(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)
    requested_model: str | None = Field(default=None, max_length=512)
    actual_model: str | None = Field(default=None, max_length=512)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    duration_ms: float = Field(ge=0)
    request_bytes: int = Field(ge=0)
    omitted_turns: int = Field(default=0, ge=0)


class ConversationEntry(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    role: Literal['user', 'assistant', 'tool']
    content: str | None
    calls: list[ConversationCall] = Field(default_factory=list, max_length=128)
    tool_call_id: str | None = None
    invocation_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    continuation_scope: str | None = Field(default=None, max_length=64)
    completion: CompletionInfo | None = None


def canonical(entry: dict) -> dict:
    value = dict(entry)
    if value.get('role') == 'assistant':
        value.setdefault('content', None)
    if 'tool_calls' in value:
        value['calls'] = [dict(id=call['id'], name=call['function']['name'],
                               arguments=call['function']['arguments'],
                               provider_metadata={'google.thought_signature': call['thought_signature']}
                               if call.get('thought_signature') else {}) for call in value.pop('tool_calls')]
    return ConversationEntry.model_validate(value).model_dump(exclude_defaults=True)


def provider_message(entry: dict, *, thought_signatures=False, continuation_scope=None) -> dict:
    record = ConversationEntry.model_validate(canonical(entry))
    result = {'role': record.role, 'content': record.content}
    if record.tool_call_id is not None:
        result['tool_call_id'] = record.tool_call_id
    if record.calls:
        result['tool_calls'] = []
        for call in record.calls:
            item = {'id': call.id, 'type': 'function', 'function': {'name': call.name, 'arguments': call.arguments}}
            signature = call.provider_metadata.get('google.thought_signature')
            if thought_signatures and signature and (continuation_scope is None or record.continuation_scope == continuation_scope):
                item['thought_signature'] = signature
            result['tool_calls'].append(item)
    return result


def bounded_history(entries: list[dict]) -> list[dict]:
    """Select complete recent turns, preserving call/result groups without rewriting history.

    Oversized current turns fail explicitly rather than silently dropping the user's
    instruction or truncating tool arguments. Historical data remains in the document.
    """
    starts = [index for index, entry in enumerate(entries) if entry.get('role') == 'user']
    if not starts:
        starts = [0] if entries else []
    total, start, turns = 0, len(entries), 0
    end = len(entries)
    for candidate in reversed(starts):
        size = sum(len(json.dumps(entry, ensure_ascii=True).encode('ascii')) for entry in entries[candidate:end])
        if total + size > MAX_CONTEXT_BYTES or turns >= MAX_CONTEXT_TURNS:
            if turns == 0:
                raise EngineError('the current conversation turn exceeds the provider context budget',
                                  hint='start a new direction with a shorter request; the full history is retained')
            break
        total += size
        start, end, turns = candidate, candidate, turns + 1
    return entries[start:]
