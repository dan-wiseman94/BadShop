import subprocess
import sys

import badshop


def test_version_attribute():
    assert badshop.__version__ == "0.1.0"


def test_module_entry_point_prints_version():
    p = subprocess.run([sys.executable, "-m", "badshop", "--version"], capture_output=True, text=True)
    assert p.returncode == 0
    assert p.stdout.strip() == "badshop 0.1.0"
