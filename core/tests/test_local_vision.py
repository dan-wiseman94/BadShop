"""On-device validation recovery stays inside the agent's bounded tool loop."""
import asyncio
import json
from unittest.mock import AsyncMock

from badshop.providers.local_vision import LocalVisionProvider
from badshop.agent.local_strategy import LocalEditStrategy
from badshop.session.session import Session
from badshop.session.models import Step


def test_invalid_image_reference_is_returned_to_model_for_repair():
    provider = LocalEditStrategy(LocalVisionProvider(AsyncMock(), lambda: True), Session.new())
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
    provider = LocalEditStrategy(LocalVisionProvider(AsyncMock(), lambda: True), Session.new())
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
    provider = LocalEditStrategy(LocalVisionProvider(AsyncMock(), lambda: True), Session.new())
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


def test_laser_geometry_uses_recorded_invocation_not_result_prose(tmp_path):
    aid = 'a' * 64
    session = Session.new()
    detector = Step(id='s1', index=1, tool='find', params={'image': aid}, actor='user', status='done',
                    data={'faces': [{'box': [0, 0, 20, 20], 'eyes': [[4, 8], [15, 8]]}]})
    session.data.steps.append(detector)
    session.data.transcript = [
        {'role': 'user', 'content': 'Laser eyes'},
        {'role': 'assistant', 'content': None, 'calls': [{'id': 'detector', 'name': 'find',
         'arguments': json.dumps({'image': aid})}]},
        {'role': 'tool', 'tool_call_id': 'detector', 'content': 'Entirely different presentation text.',
         'invocation_id': detector.invocation_id},
    ]
    from badshop.session import project
    # The invocation link survives the portable document validator too.
    validated = project._imported_transcript(tmp_path / 'test.badshop', session.data.transcript)
    assert validated[-1]['invocation_id'] == detector.invocation_id
    session.data.transcript = validated
    provider = LocalEditStrategy(LocalVisionProvider(AsyncMock(), lambda: True), session)
    provider._request = AsyncMock(return_value={'content': '{"face":1}'})
    messages = [{'role': 'user', 'content': [
        {'type': 'text', 'text': 'Laser eyes'},
        {'type': 'text', 'text': f'Artifact ID: {aid}'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}},
    ]}, {'role': 'assistant', 'tool_calls': [{'id': 'detector', 'function': {
        'name': 'find', 'arguments': json.dumps({'image': aid})}}]},
        {'role': 'tool', 'tool_call_id': 'detector', 'content': 'No structured_data delimiter.'}]
    reply = asyncio.run(provider.complete(messages, [{'function': {'name': 'find'}}], lambda _: None))
    assert reply.tool_calls[0].arguments == {'image': aid, 'at': [[4, 8], [15, 8]]}
