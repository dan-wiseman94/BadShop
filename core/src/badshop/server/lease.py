"""One live session owner per data/config directory, released even after a crash.

Lock files are stable inodes: never unlink them, including on normal shutdown. PID
files alone cannot distinguish a crashed owner from PID reuse or racing launches.
"""

import contextlib
import os
import time
from contextlib import ExitStack, contextmanager

from badshop.engine.assets import data_dir
from badshop.engine.errors import EngineError
from badshop.server.settings import config_dir


@contextmanager
def runtime_lease():
    with ExitStack() as stack:
        for directory in sorted({data_dir().resolve(), config_dir().resolve()}):
            try:
                directory.mkdir(parents=True, exist_ok=True)
                file = stack.enter_context((directory / "runtime.lock").open("a+b"))
                if os.name == "nt":
                    import msvcrt
                    # Windows byte-range locks also cover bytes beyond EOF.
                    file.seek(0)
                    # Windows can signal a terminated process before all kernel I/O
                    # cleanup (including byte-lock release) has completed.
                    for attempt in range(11):
                        try:
                            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                            break
                        except OSError:
                            if attempt == 10:
                                raise
                            time.sleep(.05)
                    def unlock(file=file):
                        with contextlib.suppress(OSError):
                            file.seek(0)
                            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                    stack.callback(unlock)
                else:
                    import fcntl
                    fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise EngineError("can't acquire the BadShop runtime lock",
                                  hint=f"close the other BadShop window or chat using {directory}; "
                                       "if none is open, check that the folder is writable") from None
        yield
