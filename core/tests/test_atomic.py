import os

import pytest

from badshop import atomic


def test_atomic_text_roundtrip_and_private_file(tmp_path):
    path = tmp_path / "nested" / "config.json"
    atomic.write_text(path, "first\n")
    atomic.write_text(path, "second: café\n")
    assert path.read_text(encoding="utf-8") == "second: café\n"
    assert list(path.parent.iterdir()) == [path]
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure", ["encoding", "replacement"])
def test_atomic_text_failure_preserves_previous_file_and_cleans_up(tmp_path, monkeypatch, failure):
    path = tmp_path / "config.json"
    path.write_bytes(b"previous")

    def fail_replace(*args):
        raise OSError("disk full")

    text = "partial text\ud800" if failure == "encoding" else "new value"
    if failure == "replacement":
        monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises((UnicodeEncodeError, OSError)):
        atomic.write_text(path, text)
    assert path.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [path]
