"""`badshop` command line."""

import argparse
import sys

from badshop import __version__


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(prog="badshop")
    p.add_argument("--version", action="version", version=f"badshop {__version__}")
    p.parse_args(argv)
    return 0
