"""On-device validation recovery stays inside the agent's bounded tool loop."""
import asyncio
from unittest.mock import AsyncMock

from badshop.providers.local_vision import LocalVisionProvider


def test_invalid_image_reference_is_returned_to_model_for_repair():
    provider = LocalVisionProvider(AsyncMock(), lambda: True)
    provider._request = AsyncMock(return_value={
        "content": "", "tool_calls": [{"id": "fixed", "function": {
            "name": "deepfry", "arguments": '{"image":"abc123","level":1}',
        }}],
    })
    messages = [
        {"role": "user", "content": "Deep fry the attached image."},
        {"role": "assistant", "tool_calls": [{"id": "bad", "function": {
            "name": "deepfry", "arguments": '{"image":"image abc123: photo"}',
        }}]},
        {"role": "tool", "tool_call_id": "bad", "content":
         "error: no such artifact: image abc123: photo\nhint: use an artifact id from a tool result"},
    ]
    reply = asyncio.run(provider.complete(messages, [{"function": {"name": "deepfry"}}], lambda _: None))
    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0].id == "fixed"
    assert provider._request.call_args.args[1]["messages"][-1] == messages[-1]


def test_failed_edit_explains_error_without_promising_a_nonexistent_step():
    provider = LocalVisionProvider(AsyncMock(), lambda: True)
    provider._request = AsyncMock()
    error = "error: invalid parameters for deepfry: level must be at least 1"
    reply = asyncio.run(provider.complete([
        {"role": "user", "content": "Deep fry this."},
        {"role": "tool", "tool_call_id": "bad", "content": error},
    ], [{"function": {"name": "deepfry"}}], lambda _: None))
    assert error in reply.text
    assert "See the step" not in reply.text
    provider._request.assert_not_called()


def test_image_schema_names_actual_context_ids_without_rewriting_model_arguments():
    aid = 'a' * 64
    provider = LocalVisionProvider(AsyncMock(), lambda: True)
    provider._request = AsyncMock(return_value={'content': '', 'tool_calls': [{
        'id': 'model', 'function': {'name': 'deepfry', 'arguments': '{"image":"invalid label"}'},
    }]})
    definition = {'type': 'function', 'function': {'name': 'deepfry', 'parameters': {
        'type': 'object', 'properties': {'image': {'type': 'string', 'format': 'badshop-image'}},
    }}}
    reply = asyncio.run(provider.complete([{'role': 'user', 'content': [
        {'type': 'text', 'text': 'Deep fry this.'},
        {'type': 'text', 'text': f'[image aaaaaaaa: photo, 128x128] Artifact ID: {aid}'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}},
    ]}], [definition], lambda _: None))
    sent = provider._request.call_args.args[1]['tools'][0]
    assert sent['function']['parameters']['properties']['image']['enum'] == [aid]
    assert 'enum' not in definition['function']['parameters']['properties']['image']
    assert reply.tool_calls[0].arguments == '{"image":"invalid label"}'
