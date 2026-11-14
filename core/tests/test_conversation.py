import copy

import pytest

from badshop.engine.errors import EngineError
from badshop.session.conversation import bounded_history, canonical, provider_message, MAX_CONTEXT_BYTES
from badshop.session import project
from badshop.session.session import Session


def test_canonical_calls_roundtrip_without_provider_envelope(tmp_path):
    legacy = {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'call', 'type': 'function', 'function': {'name': 'info', 'arguments': '{}'},
         'thought_signature': 'signed-provider-state'}]}
    record = canonical(legacy)
    assert 'tool_calls' not in record and 'function' not in record['calls'][0]
    assert record['calls'][0]['provider_metadata'] == {'google.thought_signature': 'signed-provider-state'}
    assert provider_message(record, thought_signatures=True) == legacy
    assert 'thought_signature' not in provider_message(record)['tool_calls'][0]
    session = Session.new()
    session.data.transcript = [{'role': 'user', 'content': 'inspect'}, record,
                               {'role': 'tool', 'tool_call_id': 'call', 'content': 'result'}]
    reopened = project.open_project(project.save(session, tmp_path / 'conversation.badshop'))
    assert reopened.data.transcript == session.data.transcript


def test_continuation_is_scoped_to_adapter_model_and_branch_and_scope_survives_save(tmp_path):
    record = canonical({'role': 'assistant', 'content': None, 'continuation_scope': 'a' * 64,
        'calls': [{'id': 'call', 'name': 'info', 'arguments': '{}',
                   'provider_metadata': {'google.thought_signature': 'opaque'}}]})
    assert provider_message(record, thought_signatures=True, continuation_scope='a' * 64)['tool_calls'][0]['thought_signature'] == 'opaque'
    assert 'thought_signature' not in provider_message(record, thought_signatures=True, continuation_scope='b' * 64)['tool_calls'][0]
    session = Session.new()
    session.data.transcript = [{'role': 'user', 'content': 'inspect'}, record]
    restored = project.open_project(project.save(session, tmp_path / 'scoped.badshop'))
    assert restored.data.transcript[-1] == record


def test_context_budget_preserves_whole_turns_and_retains_archived_history():
    history = []
    for index in range(100):
        history.extend([{'role': 'user', 'content': f'turn {index}'},
                        {'role': 'assistant', 'content': None,
                         'calls': [{'id': str(index), 'name': 'info', 'arguments': '{}'}]},
                        {'role': 'tool', 'tool_call_id': str(index), 'content': 'x' * 8000}])
    before = copy.deepcopy(history)
    selected = bounded_history(history)
    assert history == before and len(selected) < len(history)
    assert selected[0]['role'] == 'user' and selected[-1]['tool_call_id'] == '99'
    assert len(selected) % 3 == 0
    assert {row['calls'][0]['id'] for row in selected if row['role'] == 'assistant'} == {
        row['tool_call_id'] for row in selected if row['role'] == 'tool'}
    with pytest.raises(EngineError, match='context budget'):
        bounded_history([{'role': 'user', 'content': 'x' * (MAX_CONTEXT_BYTES + 1)}])


def test_complete_request_budget_includes_tool_schemas_and_system_text():
    from badshop.agent.context import validate_request_budget
    validate_request_budget([{'role': 'system', 'content': 'small'}], [])
    with pytest.raises(EngineError, match='context byte budget'):
        validate_request_budget([], [{'description': 'x' * (16 * 2**20)}])
    with pytest.raises(EngineError, match='context byte budget'):
        validate_request_budget([{'role': 'system', 'content': 'x' * (16 * 2**20)}], [])


def test_measured_usage_is_typed_and_roundtrips_without_prompt_or_sdk_bodies(tmp_path):
    from badshop.agent.provider import Reply
    from badshop.providers.litellm_provider import measured_reply
    reply = measured_reply(Reply('done'), {'model': 'actual-model', 'usage': {'prompt_tokens': 123, 'completion_tokens': 7},
                                         'request': {'private_prompt': 'never persist this'}})
    assert (reply.input_tokens, reply.output_tokens, reply.actual_model) == (123, 7, 'actual-model')
    unknown = measured_reply(Reply(), {'usage': {'prompt_tokens': True, 'completion_tokens': -1}})
    assert unknown.input_tokens is None and unknown.output_tokens is None
    session = Session.new()
    session.data.transcript = [canonical({'role': 'assistant', 'content': reply.text, 'completion': {
        'actual_model': reply.actual_model, 'input_tokens': reply.input_tokens, 'output_tokens': reply.output_tokens,
        'duration_ms': 20.0, 'request_bytes': 456}})]
    restored = project.open_project(project.save(session, tmp_path / 'usage.badshop'))
    assert restored.data.transcript == session.data.transcript
    assert provider_message(restored.data.transcript[0]) == {'role': 'assistant', 'content': 'done'}
