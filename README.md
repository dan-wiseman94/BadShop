# badshop

A desktop app where any vision-capable LLM makes deliberately bad, 2005-forum-style
photoshops — hard-edged cut-and-paste, Impact captions, laser eyes, deep-frying — while
you watch every step, edit its parameters, run tools yourself, or approve each call.

**Status:** the core engine and its `badshop` command line are built (Plan 1), and so is the
headless core the app will run: sessions, project files, the agent loop (driven by a scripted
stand-in model until Plan 3 adds real providers) and its local API (Plan 2). The app itself
comes next. Start with the spec:
[`docs/superpowers/specs/2026-09-26-badshop-app-design.md`](docs/superpowers/specs/2026-09-26-badshop-app-design.md)

## Running the command line

`core/` holds the Python package (`core/src/badshop/`: `engine/`, `tools/`, `cli/`,
`session/`, `agent/`, `server/`), managed with [uv](https://docs.astral.sh/uv/). Run the
CLI from the folder that holds your images, since relative paths and the `badshop_work/`
folder resolve against it:

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

## Running the core

`badshop-core` is the headless core the desktop app talks to: it holds the session (images,
steps, replay, project files) and runs the tools and the agent.

```
uv run --project /path/to/badshop/core badshop-core serve
```

(`python -m badshop.server serve` in the project's environment does the same.) It listens on
127.0.0.1 only, on a free port (`--port N` picks one), and prints exactly one line to stdout,
`{"port": 40123, "token": "<a random token>"}`; everything else goes to stderr. A client connects to
`ws://127.0.0.1:<port>` and first sends `{"type": "hello", "token": "<token>", "actor": "user"}`.
The core answers `{"type": "welcome", "actor": "user", "version": "0.1.0"}`; any other first
message (or none within 10 s) closes the connection with code 1008. After that it is JSON-RPC
2.0 in text frames: requests such as
`{"jsonrpc": "2.0", "id": 1, "method": "tools.list", "params": {}}`, and events
(`step.finished`, `approval.needed`, `turn.finished` and the rest) as notifications. The
methods and events are listed in spec §7 and `core/src/badshop/server/app.py`. Requests run
concurrently, so match replies by `id`; messages can be up to 64 MiB, so raise your client's
limit (websockets' default is 1 MiB). Closing the connection cancels the requests it is still
waiting on. Ctrl-C or SIGTERM stops the core cleanly: clients get close code 1001, a running
tool and the agent's turn stop, and the session is autosaved. When stdin is not a terminal, the
end of stdin does the same: the app starts the core with a stdin pipe, so a core whose app has
died stops too. When you script it, keep its stdin open: with stdin from `/dev/null` (which a
background job in a script gets) it stops right after the handshake line.

Until Plan 3 adds real model providers, `chat.send` plays a script: point
`BADSHOP_FAKE_PROVIDER` (or the `fake_provider_script` setting) at a JSON list of replies such
as `[{"text": "Looking for faces.", "tool_calls": [{"name": "find", "arguments": {"image": "a3f9c1d2"}}]}]`.
Settings live in the config folder (`$BADSHOP_CONFIG_DIR` overrides it), and the open session
autosaves to `autosave/session.badshop` in the data folder. On the next start the core sets that
file aside as `autosave/previous.badshop` and offers it: `session.get` reports its path as
`restorable`, and `session.restore` opens it (spec §9).
