"""Frozen core entry: spawned workers must dispatch before importing the server."""
import multiprocessing
import os

if __name__ == "__main__":
    if os.environ.get("BADSHOP_SMOKE_TRACE") == "1":
        import faulthandler
        faulthandler.dump_traceback_later(30, repeat=True)
    multiprocessing.freeze_support()
    from badshop.server.main import main
    raise SystemExit(main())
