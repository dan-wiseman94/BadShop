"""Frozen core entry: spawned workers must dispatch before importing the server."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from badshop.server.main import main
    raise SystemExit(main())
