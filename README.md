# badshop

A desktop app where any vision-capable LLM makes deliberately bad, 2005-forum-style
photoshops — hard-edged cut-and-paste, Impact captions, laser eyes, deep-frying — while
you watch every step, edit its parameters, run tools yourself, or approve each call.

**Status:** the core engine and its `badshop` command line are built (Plan 1); the app
itself comes next. Start with the spec:
[`docs/superpowers/specs/2026-09-26-badshop-app-design.md`](docs/superpowers/specs/2026-09-26-badshop-app-design.md)

## Running the command line

`core/` holds the Python package (`core/src/badshop/`: `engine/`, `tools/`, `cli/`),
managed with [uv](https://docs.astral.sh/uv/). Run the CLI from the folder that holds your
images, since relative paths and the `badshop_work/` folder resolve against it:

```
uv run --project /path/to/badshop/core badshop prep photo.jpg
uv run --project /path/to/badshop/core badshop --help      # every command
```

Or install it once as a tool (from the repository root) and drop the prefix:

```
uv tool install ./core
badshop prep photo.jpg
```

A bare `uv run badshop …` works only inside `core/`. Finished images go to
`~/Pictures/badshop/` (or `$BADSHOP_OUT`); downloaded models and fonts go to the app data
folder (or `$BADSHOP_DATA_DIR`). Tests: `cd core && uv run pytest -q`.

`reference/` holds the working CLI engine this app is built from (`badshop.py`, the
Claude Code skill that drives it, and a generated catalog of every tool and parameter).
