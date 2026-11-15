import io
import zipfile
import pytest

from PIL import Image
from badshop.engine.errors import EngineError

from badshop.session import project
from badshop.session.execution import InProcessExecutor, OutputRecord, ToolOutcome
from badshop.session.models import Source
from badshop.session.session import Session


def png(color):
    output = io.BytesIO()
    Image.new('RGB', (8, 8), color).save(output, 'PNG')
    return output.getvalue()


def test_forged_provenance_cycle_is_refused_without_changing_archive(tmp_path):
    session = Session.new()
    artifact = session.import_image(png('red'), 'source')
    session.artifacts.meta[artifact.id] = artifact.model_copy(update={'inputs': (artifact.id,)})
    path = project.save(session, tmp_path / 'cycle.badshop')
    before = path.read_bytes()
    with pytest.raises(EngineError, match='cyclic provenance'):
        project.open_project(path)
    assert path.read_bytes() == before


def test_input_admission_refuses_before_reading_or_executing_images(monkeypatch):
    from badshop.session import session as implementation
    session = Session.new()
    image = session.import_image(png('red'), 'source')
    monkeypatch.setattr(implementation, 'MAX_INPUT_BYTES', 1)
    def unexpected(*args):
        raise AssertionError('input bytes should not be read after admission is refused')
    monkeypatch.setattr(session.artifacts, 'data', unexpected)
    step = session.run_tool('info', {'image': image.id}, 'user')
    assert step.status == 'error' and 'input budget' in step.error.message


def test_distinct_import_uses_share_bytes_and_preserve_provenance(tmp_path):
    session = Session.new()
    data = png('red')
    first = session.import_image(data, 'first.png', Source(kind='url', creator='First creator'))
    second = session.import_image(data, 'second.png', Source(kind='url', creator='Second creator'))
    assert first.id != second.id
    assert first.blob_id == second.blob_id
    assert session.artifacts._data[first.id] == session.artifacts._data[second.id]
    path = project.save(session, tmp_path / 'uses.badshop')
    with zipfile.ZipFile(path) as archive:
        assert len([name for name in archive.namelist() if name.startswith('artifacts/')]) == 1
    restored = project.open_project(path)
    assert restored.artifacts.meta[first.id].source.creator == 'First creator'
    assert restored.artifacts.meta[second.id].source.creator == 'Second creator'
    assert restored.artifacts.data(first.id) == restored.artifacts.data(second.id) == data
    restored.artifacts.drop([first.id])
    assert restored.artifacts.data(second.id) == data


class Ports:
    names = ['left', 'right']

    def run(self, call, cancel=None):
        if call.tool != 'filter':
            return InProcessExecutor().run(call, cancel)
        return ToolOutcome(True, [OutputRecord(name, png('red' if name == 'left' else 'blue'), name + '.png')
                                  for name in self.names])


def test_replay_follows_names_and_missing_output_stays_unresolved_after_reopen(tmp_path):
    executor = Ports()
    session = Session.new(executor=executor)
    source = session.import_image(png('green'), 'source.png')
    producer = session.run_tool('filter', {'image': source.id, 'names': ['invert']}, 'user')
    consumer = session.run_tool('info', {'image': producer.output_ports['right']}, 'user')
    executor.names = ['right', 'left']
    session.replay_from(producer.id, use_cache=False)
    assert consumer.params['image'] == producer.output_ports['right']
    assert session.artifacts.data(consumer.params['image']) == png('blue')
    executor.names = ['left']
    session.replay_from(producer.id, use_cache=False)
    assert consumer.status == 'error'
    assert 'no longer available' in consumer.error.message
    restored = project.open_project(project.save(session, tmp_path / 'missing.badshop'))
    restored.replay_from(consumer.id, use_cache=False)
    assert restored.step(consumer.id).status == 'error'
    assert 'no longer available' in restored.step(consumer.id).error.message


def test_editing_text_keeps_a_missing_input_port_unresolved():
    executor = Ports()
    session = Session.new(executor=executor)
    source = session.import_image(png('green'), 'source.png')
    producer = session.run_tool('filter', {'image': source.id, 'names': ['invert']}, 'user')
    layout = session.run_tool('layout', {
        'template': 'desktop-error', 'images': [producer.output_ports['right']], 'title': 'First',
    }, 'user')
    executor.names = ['left']
    session.replay_from(producer.id, use_cache=False)
    assert layout.status == 'error'
    session.edit(layout.id, {**layout.params, 'title': 'Revised'})
    session.replay_from(layout.id)
    assert layout.status == 'error' and "'right' is no longer available" in layout.error.message
    session.edit(layout.id, {**layout.params, 'images': [source.id]})
    session.replay_from(layout.id)
    assert layout.status == 'done'
    assert layout.params['title'] == 'Revised'


def test_acquired_members_follow_source_evidence_instead_of_search_position():
    class Acquired:
        names = ['red', 'blue']
        def run(self, call, cancel=None):
            if call.tool != 'fetch':
                return InProcessExecutor().run(call, cancel)
            return ToolOutcome(True, [OutputRecord(str(i), png(name), name + '.png')
                                      for i, name in enumerate(self.names)], data={'sources': [
                {'kind': 'url', 'url': f'https://example.org/{name}.png'} for name in self.names]})
    executor = Acquired()
    session = Session.new(executor=executor)
    source = session.run_tool('fetch', {'query': 'colors'}, 'user')
    reader = session.run_tool('info', {'image': source.outputs[1]}, 'user')
    blue = session.artifacts.data(reader.params['image'])
    executor.names = ['blue', 'red']
    session.replay_from(source.id, use_cache=False)
    assert session.artifacts.data(reader.params['image']) == blue
    executor.names = ['red']
    session.replay_from(source.id, use_cache=False)
    assert reader.status == 'error' and 'no longer available' in reader.error.message
