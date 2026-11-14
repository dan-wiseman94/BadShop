import gc
from pathlib import Path

import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.session.artifacts import ArtifactStore
from test_artifacts import encode


def test_disk_storage_fork_and_cleanup():
    store = ArtifactStore()
    raw = encode(Image.new('RGB', (12, 8), 'red'))
    meta = store.add(raw, 'original')
    path = store._data[meta.id]
    assert isinstance(path, Path) and path.read_bytes() == raw
    fork = store.fork()
    store.drop([meta.id])
    assert not path.exists()
    assert fork.data(meta.id) == raw
    root = fork._blobs.root
    del fork
    gc.collect()
    assert not root.exists()


def test_failed_batch_removes_published_files():
    store = ArtifactStore()
    with pytest.raises(RuntimeError), store.atomic():
        store.add(encode(Image.new('RGB', (12, 8), 'red')), 'temporary')
        raise RuntimeError('failure after publication')
    assert not store.ids()
    assert list(store._blobs.root.iterdir()) == []


def test_corrupt_blob_fails_before_decode():
    store = ArtifactStore()
    meta = store.add(encode(Image.new('RGB', (12, 8), 'red')), 'original')
    store._data[meta.id].write_bytes(b'corrupted')
    with pytest.raises(EngineError, match='integrity'):
        store.data(meta.id)
