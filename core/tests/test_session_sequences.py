"""Generated session action sequences with an independent, tiny pixel/branch model."""
import hashlib
import io
from pathlib import Path
import tempfile
from unittest.mock import patch

from hypothesis import settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule
from PIL import Image
import pytest

from badshop.engine.errors import EngineError
from badshop.session import branches, project
from badshop.session.session import Session


class SessionSequences(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.temporary = tempfile.TemporaryDirectory(prefix='badshop-sequences-')
        self.root = Path(self.temporary.name)
        self.path = self.root / 'session.badshop'
        self.session = Session.new(output_dir=self.root)
        # RGB triples with varied channels; expected inversion is byte arithmetic,
        # independent of the engine and of the generated artifact hashes.
        self.pixels = bytes((i * 37) % 256 for i in range(8 * 6 * 3))
        image = Image.frombytes('RGB', (8, 6), self.pixels)
        buffer = io.BytesIO()
        image.save(buffer, 'PNG')
        self.base = self.session.import_image(buffer.getvalue(), 'source').id
        first = self.session.run_tool('filter', {'image': self.base, 'names': ['invert']}, 'user')
        second = self.session.run_tool('filter', {'image': first.outputs[0], 'names': ['invert']}, 'user')
        assert first.status == second.status == 'done'
        branches.create(self.session, 'Variant')
        self.expected = {key: [1, 1] for key in self.session.data.branches}
        self.imports = {key: {self.base} for key in self.expected}
        project.save(self.session, self.path)

    @rule(position=st.integers(0, 1), inversions=st.integers(1, 2))
    def edit_and_replay(self, position, inversions):
        step = self.session.data.steps[position]
        self.session.edit(step.id, {**step.params, 'names': ['invert'] * inversions})
        self.session.replay_from(step.id)
        self.expected[self.session.data.active_branch_id][position] = inversions

    @rule(channel=st.integers(0, 255))
    def import_image(self, channel):
        buffer = io.BytesIO()
        Image.new('RGB', (2, 3), (channel, 10, 20)).save(buffer, 'PNG')
        image = self.session.import_image(buffer.getvalue(), 'another source')
        self.imports[self.session.data.active_branch_id].add(image.id)

    @precondition(lambda self: len(self.expected) < 4)
    @rule()
    def branch(self):
        previous = self.session.data.active_branch_id
        branches.create(self.session, f'Variant {len(self.expected)}')
        active = self.session.data.active_branch_id
        self.expected[active] = self.expected[previous].copy()
        self.imports[active] = self.imports[previous].copy()

    @rule(index=st.integers(0, 3))
    def switch(self, index):
        branches.switch(self.session, list(self.expected)[index % len(self.expected)])

    @rule()
    def reject(self):
        before = set(self.session.artifacts.ids())
        step = self.session.propose('filter', {'image': self.base, 'names': ['invert']}, 'agent:fake')
        self.session.reject(step.id, 'cancelled by user')
        assert step.status == 'rejected' and not step.outputs
        assert set(self.session.artifacts.ids()) == before

    @rule()
    def save_and_reopen(self):
        project.save(self.session, self.path)
        self.session = project.open_project(self.path, output_dir=self.root)

    @rule()
    def failed_save(self):
        previous = self.path.read_bytes()
        state = self.session.data.model_dump()
        with patch('badshop.session.project.os.replace', side_effect=OSError('injected disk failure')):
            with pytest.raises(EngineError, match="can't save"):
                project.save(self.session, self.path)
        assert self.path.read_bytes() == previous
        assert self.session.data.model_dump() == state
        assert sorted(p.name for p in self.root.iterdir()) == ['session.badshop']

    @invariant()
    def outputs_and_branch_ownership_match_model(self):
        active = self.session.data.active_branch_id
        known_imports = set().union(*self.imports.values())
        assert set(self.session.data.branches) == set(self.expected)
        for branch_id, counts in self.expected.items():
            branch = self.session.data.branches[branch_id]
            steps = self.session.data.steps if branch_id == active else branch.steps
            visible = self.session.visible_artifact_ids() if branch_id == active else set(branch.artifact_ids)
            assert known_imports & visible == self.imports[branch_id]
            parity = 0
            for step, count in zip(steps[:2], counts, strict=True):
                parity = (parity + count) % 2
                assert step.status == 'done'
                data = self.session.artifacts.data(step.outputs[0])
                assert hashlib.sha256(data).hexdigest() == step.outputs[0]
                with Image.open(io.BytesIO(data)) as image:
                    assert image.size == (8, 6)
                    expected = bytes(255 - value for value in self.pixels) if parity else self.pixels
                    assert image.convert('RGB').tobytes() == expected
            assert steps[1].params['image'] == steps[0].outputs[0]
            assert all(step.status == 'rejected' and not step.outputs for step in steps[2:])

    def teardown(self):
        self.temporary.cleanup()


TestSessionSequences = SessionSequences.TestCase
TestSessionSequences.settings = settings(max_examples=20, stateful_step_count=20,
                                         deadline=None, derandomize=True, print_blob=True)
