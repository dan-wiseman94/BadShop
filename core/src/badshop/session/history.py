"""Immutable document history records and structurally shared list membership.

Branch heads own roots in this graph. Only activation materializes editable
records; capturing a checkpoint never copies historical model objects.
"""

import hashlib
import json

from badshop.engine.errors import EngineError

FANOUT = 32
MAX_EXPANDED_BYTES = 16 * 2**20


def _node(nodes: dict[str, str], kind: str, value) -> str:
    raw = json.dumps([kind, value], ensure_ascii=True, separators=(',', ':'), allow_nan=False)
    key = hashlib.sha256(raw.encode('ascii')).hexdigest()
    if key in nodes and nodes[key] != raw:
        raise EngineError('history record failed integrity verification')
    nodes[key] = raw
    return key


def capture(nodes: dict[str, str], state: dict) -> str:
    fields = {}
    for field in ('steps', 'messages', 'transcript'):
        records = [_node(nodes, 'record', item) for item in state[field]]
        level = [_node(nodes, 'list', records[i:i + FANOUT]) for i in range(0, len(records), FANOUT)]
        while len(level) > FANOUT:
            level = [_node(nodes, 'concat', level[i:i + FANOUT]) for i in range(0, len(level), FANOUT)]
        fields[field] = _node(nodes, 'concat', level)
    return _node(nodes, 'state', fields)


def _read_node(nodes, key):
    try:
        raw = nodes.get(key)
        if raw is None or hashlib.sha256(raw.encode('ascii')).hexdigest() != key:
            raise EngineError('history record failed integrity verification')
        kind, value = json.loads(raw)
        valid = (
            kind == 'record' and isinstance(value, dict)
            or kind in ('list', 'concat') and isinstance(value, list) and len(value) <= FANOUT
            and all(isinstance(ref, str) for ref in value)
            or kind == 'state' and isinstance(value, dict) and set(value) == {'steps', 'messages', 'transcript'}
            and all(isinstance(ref, str) for ref in value.values())
        )
        if not valid:
            raise EngineError('invalid history record')
        return kind, value, len(raw)
    except (TypeError, ValueError, UnicodeError, AttributeError) as error:
        raise EngineError('invalid history graph', hint=str(error)) from None


def materialize(nodes: dict[str, str], root: str) -> dict:
    budget = 0

    def read(key, expected, depth=0):
        nonlocal budget
        if depth > 32:
            raise EngineError('history graph is too deeply nested')
        kind, value, size = _read_node(nodes, key)
        budget += size
        if budget > MAX_EXPANDED_BYTES:
            raise EngineError('history revision is too large')
        if kind not in expected:
            raise EngineError('invalid history record type')
        if kind == 'record' and isinstance(value, dict):
            return value
        if kind == 'list' and isinstance(value, list) and len(value) <= FANOUT:
            return [read(item, ('record',), depth + 1) for item in value]
        if kind == 'concat' and isinstance(value, list) and len(value) <= FANOUT:
            return [item for ref in value for item in read(ref, ('list', 'concat'), depth + 1)]
        if kind == 'state' and isinstance(value, dict) and set(value) == {'steps', 'messages', 'transcript'}:
            return {name: read(ref, ('list', 'concat'), depth + 1) for name, ref in value.items()}
        raise EngineError('invalid history record')

    try:
        state = read(root, ('state',))
        if not isinstance(state, dict) or set(state) != {'steps', 'messages', 'transcript'}:
            raise EngineError('invalid history revision')
        return state
    except (TypeError, ValueError, UnicodeError) as error:
        raise EngineError('invalid history graph', hint=str(error)) from None


def collect(nodes: dict[str, str], roots: list[str]) -> None:
    """Mark all retained heads before deleting anything. Invalid graphs stop GC."""
    checked = {}

    def visit(key, expected, depth=0):
        if depth > 32:
            raise EngineError('history graph is too deeply nested')
        if key in checked:
            kind, cost, height = checked[key]
            if kind not in expected:
                raise EngineError('invalid history record type')
            if depth + height > 32:
                raise EngineError('history graph is too deeply nested')
            return cost, height
        kind, value, cost = _read_node(nodes, key)
        if kind not in expected:
            raise EngineError('invalid history record type')
        children = []
        if kind == 'state':
            children = [visit(ref, ('list', 'concat'), depth + 1) for ref in value.values()]
        elif kind == 'concat':
            children = [visit(ref, ('list', 'concat'), depth + 1) for ref in value]
        elif kind == 'list':
            children = [visit(ref, ('record',), depth + 1) for ref in value]
        cost += sum(child_cost for child_cost, _ in children)
        height = max((child_height + 1 for _, child_height in children), default=0)
        if cost > MAX_EXPANDED_BYTES:
            raise EngineError('history revision is too large')
        checked[key] = kind, cost, height
        return cost, height

    for root in roots:
        visit(root, ('state',))
    for key in set(nodes) - checked.keys():
        del nodes[key]


def migrate(payload: dict) -> dict:
    """Schema 1–4 import only. Preserve the source archive; never execute tools."""
    if payload.get('schema', 1) >= 5:
        return payload
    if not isinstance(payload.get('branches', {}), dict) or any(
        not isinstance(payload.get(name, []), list) for name in ('manual_undo', 'manual_redo')
    ):
        raise EngineError('invalid legacy history')
    nodes = {}
    for branch in [*payload.get('branches', {}).values(), *payload.get('manual_undo', []), *payload.get('manual_redo', [])]:
        if not isinstance(branch, dict):
            raise EngineError('invalid legacy history')
        state = {name: branch.pop(name, []) for name in ('steps', 'messages', 'transcript')}
        if any(not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows) for rows in state.values()):
            raise EngineError('invalid legacy history')
        branch['revision'] = capture(nodes, state)
        for field, prefix, name in [('steps', 's', 'max_step_number'), ('messages', 'm', 'max_message_number')]:
            ids = [row.get('id', '') for row in state[field]]
            branch[name] = max((int(value[1:]) for value in ids if isinstance(value, str)
                               and value.startswith(prefix) and value[1:].isascii()
                               and value[1:].isdigit() and len(value) <= 10), default=0)
    payload['history_nodes'] = nodes
    payload['schema'] = 5
    return payload
