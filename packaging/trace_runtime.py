"""Opt-in frozen bootstrap tracing, installed before PyInstaller's package hooks."""

import os
import sys

if os.environ.get("BADSHOP_SMOKE_TRACE") == "1":
    import faulthandler

    # Keep the descriptor alive through every subsequent runtime hook. In Windows
    # multiprocessing children stderr is not inherited, so it cannot carry a dump.
    _badshop_trace_folder = os.environ["BADSHOP_LOG_DIR"]
    os.makedirs(_badshop_trace_folder, exist_ok=True)
    _badshop_bootstrap_trace = open(  # noqa: SIM115 - faulthandler needs a process-lifetime descriptor
        os.path.join(_badshop_trace_folder, f"frozen-{os.getpid()}.trace.log"),
        "a", encoding="utf-8", buffering=1,
    )
    print(f"pid={os.getpid()} parent={os.getppid()} "
          f"spawn_worker={'--multiprocessing-fork' in sys.argv} before PyInstaller package runtime hooks",
          file=_badshop_bootstrap_trace)
    faulthandler.enable(file=_badshop_bootstrap_trace, all_threads=True)
    faulthandler.dump_traceback_later(15, repeat=True, file=_badshop_bootstrap_trace)
