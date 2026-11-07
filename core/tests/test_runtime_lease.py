"""Real process locks, including forced termination and overlapping directory sets."""
import os
import subprocess
import sys

import pytest

from badshop.engine.errors import EngineError
from badshop.server.lease import runtime_lease
from badshop.session import project
from badshop.session.session import Session


@pytest.mark.parametrize("shared", ["data", "config", "both"])
def test_competitor_refused_and_crashed_owner_released(tmp_path, monkeypatch, shared):
    data, config = tmp_path / "data", tmp_path / "config"
    monkeypatch.setenv("BADSHOP_DATA_DIR", str(data))
    monkeypatch.setenv("BADSHOP_CONFIG_DIR", str(config))
    code = ("from badshop.server.lease import runtime_lease\n"
            "import sys\nwith runtime_lease():\n print('locked', flush=True)\n sys.stdin.read()\n")
    owner = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             env=dict(os.environ))
    try:
        assert owner.stdout.readline().strip() == "locked"
        if shared == "data":
            monkeypatch.setenv("BADSHOP_CONFIG_DIR", str(tmp_path / "other-config"))
        elif shared == "config":
            monkeypatch.setenv("BADSHOP_DATA_DIR", str(tmp_path / "other-data"))
        with pytest.raises(EngineError, match="runtime lock"):
            with runtime_lease():
                pytest.fail("two owners acquired the same runtime directory")
        owner.kill()
        owner.wait(timeout=10)
        with runtime_lease():
            pass
        # Failed partial acquisition and successful shutdown release all locks.
        with runtime_lease():
            pass
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.communicate(timeout=10)


def test_hard_kill_before_project_commit_preserves_previous_save(tmp_path):
    path = tmp_path / "work.badshop"
    original = Session.new()
    project.save(original, path)
    before = path.read_bytes()
    code = ("from badshop.session import project\n"
            "from badshop.session.session import Session\nimport sys\n"
            "def interrupted(*args):\n print('before commit', flush=True)\n sys.stdin.read()\n"
            "project.os.replace = interrupted\nproject.save(Session.new(), sys.argv[1])\n")
    writer = subprocess.Popen([sys.executable, "-c", code, str(path)], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert writer.stdout.readline().strip() == "before commit"
        writer.kill()
        writer.wait(timeout=10)
        assert path.read_bytes() == before
        assert project.open_project(path).data.id == original.data.id
        replacement = Session.new()
        project.save(replacement, path)
        assert project.open_project(path).data.id == replacement.data.id
    finally:
        if writer.poll() is None:
            writer.kill()
        writer.communicate(timeout=10)
