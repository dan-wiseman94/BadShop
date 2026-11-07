import subprocess
import sys
from importlib.metadata import version

import badshop


def test_version_attribute():
    assert badshop.__version__ == version("badshop")


def test_module_entry_point_prints_version():
    p = subprocess.run([sys.executable, "-m", "badshop", "--version"], capture_output=True, text=True)
    assert p.returncode == 0
    assert p.stdout.strip() == f"badshop {badshop.__version__}"
