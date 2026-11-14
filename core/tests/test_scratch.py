import json
import subprocess
import sys
from pathlib import Path

from badshop.session import scratch


def test_killed_owner_is_collected_but_live_unknown_and_recent_are_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(scratch.tempfile, 'tempdir', str(tmp_path))
    with scratch.temporary('blobs') as alive:
        (Path(alive) / 'pixels').write_bytes(b'live bytes')
        unknown = tmp_path / 'badshop-blobs-abcdefgh'
        unknown.mkdir()
        (unknown / 'evidence').write_bytes(b'not ours')
        child = subprocess.Popen([sys.executable, '-c',
            'import tempfile,sys,time; from pathlib import Path; from badshop.session import scratch; '
            'tempfile.tempdir=sys.argv[1]; d=scratch.temporary("media"); '
            '(Path(d.name)/"pixels").write_bytes(b"private copy"); print(d.name,flush=True); time.sleep(60)',
            str(tmp_path)], stdout=subprocess.PIPE, text=True)
        try:
            dead = Path(child.stdout.readline().strip())
            assert dead.parent == tmp_path
            child.kill()
            child.wait(timeout=10)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
            child.stdout.close()
        scratch.collect(tmp_path)  # fresh interrupted work gets the grace period
        assert dead.exists()
        scratch.collect(tmp_path, grace_seconds=0)
        assert not dead.exists()
        assert (Path(alive) / 'pixels').read_bytes() == b'live bytes'
        assert (unknown / 'evidence').read_bytes() == b'not ours'
        # An unreadable owner is evidence to preserve, not permission to delete.
        (unknown / scratch.MARKER).write_text(json.dumps({'version': 1, 'pid': -1, 'started': 0, 'created': 0}))
        scratch.collect(tmp_path, grace_seconds=0)
        assert unknown.exists()
