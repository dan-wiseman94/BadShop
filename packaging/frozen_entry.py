"""Frozen core entry: spawned workers must dispatch before importing the server."""
import multiprocessing
import os

if __name__ == "__main__":
    _trace = None
    if os.environ.get("BADSHOP_SMOKE_TRACE") == "1":
        import faulthandler
        import sys
        from pathlib import Path

        # Windows multiprocessing children do not inherit the parent's stderr handle.
        # Keep one independent descriptor alive per PID, so both workers and the core
        # can explain an import/bootstrap stall before the smoke harness kills them.
        _folder = Path(os.environ["BADSHOP_LOG_DIR"])
        _folder.mkdir(parents=True, exist_ok=True)
        _trace = (_folder / f"frozen-{os.getpid()}.trace.log").open("a", encoding="utf-8", buffering=1)
        print(f"pid={os.getpid()} parent={os.getppid()} "
              f"spawn_worker={'--multiprocessing-fork' in sys.argv} entering freeze_support", file=_trace)
        faulthandler.enable(file=_trace, all_threads=True)
        faulthandler.dump_traceback_later(15, repeat=True, file=_trace)
    multiprocessing.freeze_support()
    if _trace is not None:
        print("freeze_support returned; importing server", file=_trace)
    from badshop.server.main import main
    if _trace is not None:
        print("server imported; running main", file=_trace)
    raise SystemExit(main())
