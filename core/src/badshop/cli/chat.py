"""A terminal client of CoreApp's JSON-RPC API, with the same sessions and approval gate as the UI."""

import argparse
import asyncio
import json
import io
import os
import sys
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TextIO

from badshop.engine.errors import EngineError

HELP = ("Type a request, or /import PATH, /save [PATH], /open PATH, /restore, /retry, /quit.\n"
        "Ctrl-C stops the current work and exits; the session is autosaved.")


def user_path(value: str) -> str:
    try:
        return str(Path(value).expanduser().resolve())
    except (OSError, RuntimeError, ValueError):
        raise EngineError("can't resolve that path",
                          hint="use a valid local path; check home-directory names and symbolic links") from None


def add_parser(sub) -> None:
    p = sub.add_parser("chat", help="art-direct a session from the terminal")
    source = p.add_mutually_exclusive_group()
    source.add_argument("--profile", help="saved provider profile id")
    source.add_argument("--model", help="LiteLLM model, e.g. openai/MODEL or ollama_chat/MODEL")
    p.add_argument("--api-base", help="API base URL for a local or compatible provider")
    p.add_argument("--api-key-env", help="environment variable holding the API key (never saved)")
    p.add_argument("--kind", choices=["api", "local", "openai_compatible"])
    p.add_argument("--supports-vision", action=argparse.BooleanOptionalAction, default=None,
                   help="override the model's image capability")
    p.add_argument("--supports-tools", action=argparse.BooleanOptionalAction, default=None,
                   help="override the model's tool-call capability")
    p.add_argument("--approval-mode", choices=["auto", "ask_changes", "ask_all"])
    p.add_argument("--image", action="append", default=[], metavar="PATH", help="import an image (repeatable)")


def _decode_line(data: bytes, stream) -> str:
    if not data:
        raise EOFError
    return data.decode(stream.encoding or "utf-8", errors=stream.errors or "strict").removesuffix("\n").removesuffix("\r")


def _raw_line(stream) -> str:
    """Read without acquiring a Python buffered-stdio lock.

    Windows consoles need CPython's raw wide-character console adapter for Unicode and
    native line editing. Its four-byte minimum can hold one full UTF-8 character. Redirected
    pipes and files use os.read, honoring the text stream's configured codec on decode.
    """
    raw = getattr(getattr(stream, "buffer", None), "raw", None)
    console = type(raw).__name__ == "_WindowsConsoleIO"
    fd = None if console else stream.fileno()
    data = bytearray()
    while chunk := raw.read(4) if console else os.read(fd, 1):
        data.extend(chunk)
        if data.endswith(b"\n"):
            break
    return _decode_line(bytes(data), stream)


async def read_input(prompt: str) -> str:
    """Cancelable terminal input with no background ownership of buffered stdio.

    POSIX uses fd readiness and removes its reader on cancellation. Windows' event loop
    cannot watch console/pipe fds, so its daemon reads only raw bytes; a cancelled request
    never retains a buffered stdin/stdout lock during interpreter shutdown.
    """
    print(prompt, end="", flush=True)  # only the event-loop thread writes buffered stdout
    stream = sys.stdin
    if isinstance(stream, io.StringIO):
        line = stream.readline()
        if not line:
            raise EOFError
        return line.removesuffix("\n").removesuffix("\r")
    loop = asyncio.get_running_loop()
    result = loop.create_future()

    def finish(value=None, error=None):
        if not result.done():
            if error is not None:
                result.set_exception(error)
            else:
                result.set_result(value)

    if os.name != "nt":
        fd = stream.fileno()
        data = bytearray()

        def ready():
            try:
                chunk = os.read(fd, 1)
                data.extend(chunk)
                if not chunk or chunk == b"\n":
                    loop.remove_reader(fd)
                    finish(_decode_line(bytes(data), stream))
            except Exception as exc:
                loop.remove_reader(fd)
                finish(error=exc)

        try:
            loop.add_reader(fd, ready)
        except PermissionError:  # epoll cannot watch a redirected regular file; its reads never wait
            return _raw_line(stream)
        try:
            return await result
        finally:
            loop.remove_reader(fd)

    def read():
        try:
            value, error = _raw_line(stream), None
        except Exception as exc:
            value, error = None, exc
        try:
            loop.call_soon_threadsafe(finish, value, error)
        except RuntimeError:  # cancellation closed the loop while an unbuffered Windows read waited
            pass

    threading.Thread(target=read, daemon=True, name="badshop-input").start()
    return await result


class TerminalClient:
    def __init__(self, app, read: Callable[[str], Awaitable[str]] = read_input,
                 output: TextIO | None = None):
        self.app, self.read = app, read
        self.output = output if output is not None else sys.stdout
        self.events: asyncio.Queue[dict] = asyncio.Queue()
        self.attachments: list[str] = []
        self._request_id = 0

    def say(self, text: str = "", *, end: str = "\n") -> None:
        print(text, file=self.output, end=end, flush=True)

    async def receive(self, raw: str) -> None:
        await self.events.put(json.loads(raw))

    async def rpc(self, method: str, **params):
        self._request_id += 1
        raw = await self.app.dispatcher.handle(json.dumps({
            "jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}), "user")
        answer = json.loads(raw)
        if "error" in answer:
            e = answer["error"]
            raise EngineError(e["message"], hint=(e.get("data") or {}).get("hint"))
        return answer["result"]

    def error(self, e: EngineError) -> None:
        self.say(f"error: {e.message}")
        if e.hint:
            self.say(f"hint: {e.hint}")

    async def configure(self, args) -> None:
        if not args.model and any((args.api_base, args.api_key_env, args.kind,
                                   args.supports_vision is not None, args.supports_tools is not None)):
            raise EngineError("provider options need --model", hint="use --model, or select --profile ID")
        if args.model:
            overrides = {name: value for name, value in (
                ("vision", args.supports_vision), ("tool_calls", args.supports_tools)) if value is not None}
            profile = {"label": args.model, "model": args.model,
                       "kind": args.kind or ("openai_compatible" if args.api_base else "api"),
                       "capability_overrides": overrides}
            if args.api_base:
                profile["api_base"] = args.api_base
            if args.api_key_env:
                profile["api_key_env"] = args.api_key_env
            saved = await self.rpc("providers.save", profile=profile)
            await self.rpc("providers.select", profile_id=saved["id"])
            self.say(f"Provider saved: {saved['id']} (reuse with --profile {saved['id']})")
        elif args.profile:
            await self.rpc("providers.select", profile_id=args.profile)
        if args.approval_mode:
            await self.rpc("session.set_approval_mode", mode=args.approval_mode)
        for path in args.image:
            await self.import_image(path)

    async def import_image(self, path: str) -> None:
        result = await self.rpc("artifacts.import", path=user_path(path))
        meta = result["working"]
        if meta["id"] not in self.attachments:
            self.attachments.append(meta["id"])
        self.say(f"image {meta['id'][:8]}: {meta['label']} ({meta['width']}x{meta['height']})")

    async def approve(self, step: dict) -> None:
        self.say(f"\n{step['id']}: {step['tool']} {json.dumps(step['params'], ensure_ascii=False)}")
        while True:
            choice = (await self.read("Approve [y], reject [n], or edit [e]? ")).strip().lower()
            if choice in ("y", "yes", "n", "no", ""):
                await self.rpc("approval.respond", step_id=step["id"],
                               decision="approve" if choice in ("y", "yes") else "reject")
                return
            if choice == "e":
                try:
                    params = json.loads(await self.read("Replacement parameters (JSON object): "))
                    if not isinstance(params, dict):
                        raise ValueError("parameters must be a JSON object")
                    await self.rpc("approval.respond", step_id=step["id"], decision="edit", params=params)
                    return
                except (ValueError, RecursionError) as e:
                    self.say(f"invalid JSON parameters: {e}")
                except EngineError as e:
                    self.error(e)
            else:
                self.say("Choose y, n, or e. Enter rejects the call.")

    async def turn(self, text: str | None = None) -> None:
        # Drain notifications from session imports/open; all upcoming turn events follow the request.
        while not self.events.empty():
            self.events.get_nowait()
        if text is not None:
            await self.rpc("chat.send", text=text, attachments=list(self.attachments))
            self.attachments.clear()
        else:
            await self.rpc("chat.retry")
        while True:
            event = await self.events.get()
            method, params = event["method"], event["params"]
            if method == "message.delta":
                self.say(params["text"], end="")
            elif method == "approval.needed":
                await self.approve(params["step"])
            elif method in ("step.finished", "step.failed"):
                step = params.get("step", params)
                self.say(f"\n[{step.get('id', '?')}: {step.get('tool', '')} {step.get('status', '')}]")
                if step.get("result_text"):
                    self.say(step["result_text"])
            elif method == "turn.finished":
                self.say()
                if params["reason"] != "done":
                    self.say(f"Turn ended: {params['reason']}" +
                             (f" — {params['error']}" if params.get("error") else ""))
                return

    async def command(self, line: str) -> bool:
        """False ends the terminal session. Paths may contain spaces; quotes are unnecessary."""
        command, _, arg = line.partition(" ")
        arg = arg.strip()
        if command in ("/quit", "/exit"):
            return False
        if command == "/help":
            self.say(HELP)
        elif command == "/retry":
            await self.turn()
        elif command == "/restore":
            await self.rpc("session.restore")
            self.attachments.clear()
            self.say("Session restored.")
        elif command == "/save":
            result = (await self.rpc("session.save_as", path=user_path(arg))
                      if arg else await self.rpc("session.save"))
            self.say(f"Saved {result['path']}")
        elif command == "/open" and arg:
            await self.rpc("session.open", path=user_path(arg))
            self.attachments.clear()
            self.say("Session opened.")
        elif command == "/import" and arg:
            await self.import_image(arg)
        else:
            self.say(HELP)
        return True

    async def run(self, args) -> int:
        unsubscribe = self.app.subscribe(self.receive)
        try:
            await self.configure(args)
            self.say(HELP)
            snapshot = await self.rpc("session.get")
            if snapshot.get("restorable"):
                self.say("An autosaved session is available: /restore")
            while True:
                try:
                    line = (await self.read("badshop> ")).strip()
                    if not line:
                        continue
                    if line.startswith("/"):
                        if not await self.command(line):
                            return 0
                    else:
                        await self.turn(line)
                except EngineError as e:
                    self.error(e)
        except EOFError:
            return 0
        finally:
            unsubscribe()
            await self.app.close()


def run_command(args) -> int:
    from badshop.server.app import CoreApp

    async def run():
        return await TerminalClient(CoreApp()).run(args)

    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 130
    except (EngineError, OSError) as e:
        print(getattr(e, "message", str(e)), file=sys.stderr)
        if getattr(e, "hint", None):
            print(f"hint: {e.hint}", file=sys.stderr)
        return 1
