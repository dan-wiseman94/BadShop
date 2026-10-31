"""Frozen core entry: spawned workers must dispatch before importing the server."""

import multiprocessing
import os


def _stage(message: str) -> None:
    if os.environ.get("BADSHOP_SMOKE_TRACE") == "1":
        # The first runtime hook owns faulthandler and its process-lifetime descriptor.
        # Entry stages append briefly without installing a second traceback timer.
        path = os.path.join(os.environ["BADSHOP_LOG_DIR"], f"frozen-{os.getpid()}.trace.log")
        with open(path, "a", encoding="utf-8") as trace:
            print(message, file=trace)


if __name__ == "__main__":
    _stage("entry: entering freeze_support")
    multiprocessing.freeze_support()
    _stage("freeze_support returned; importing server")
    from badshop.server.main import main
    _stage("server imported; running main")
    raise SystemExit(main())
