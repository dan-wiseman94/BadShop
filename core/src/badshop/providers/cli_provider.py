"""Subscription agents own their loop; badshop supplies only session tools through MCP.

Only --help/--version and Codex's bundled catalog are queried during discovery. No login,
installation or paid prompt is attempted. Private configuration never modifies user settings.
"""

import asyncio
import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from collections import deque
from collections.abc import Callable
from pathlib import Path

from badshop.agent.context import SYSTEM_PROMPT
from badshop.agent.provider import ProviderError
from badshop.providers.profiles import Profile

CLIS = ("claude", "codex", "gemini")
MAX_LINE = 8 * 2**20


def find_executable(cli: str, executable: str | None = None) -> str | None:
    if executable:
        path = Path(executable).expanduser()
        return str(path) if path.is_file() and os.access(path, os.X_OK) else None
    found = shutil.which(cli)
    if found:
        return found
    # GUI processes on macOS often lack the login shell's PATH.
    for folder in (Path.home() / ".local/bin", Path.home() / ".npm-global/bin",
                   Path("/opt/homebrew/bin"), Path("/usr/local/bin")):
        path = folder / (cli + (".exe" if os.name == "nt" else ""))
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def _inspect(executable: str, *args: str) -> str:
    try:
        result = subprocess.run([executable, *args], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=12)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ProviderError(f"can't inspect {Path(executable).name}: {e}") from None
    if result.returncode:
        raise ProviderError(f"{Path(executable).name} inspection failed: {result.stderr[-1000:]}")
    return result.stdout


def inspect_cli(cli: str, executable: str | None = None) -> dict:
    path = find_executable(cli, executable)
    info = {"cli": cli, "executable": path, "version": None, "available": bool(path),
            "supported": False, "experimental": cli == "gemini"}
    if not path:
        return {**info, "error": f"{cli} was not found; install it or choose its executable"}
    try:
        version = _inspect(path, "--version").strip().splitlines()
        info["version"] = version[0] if version else "unknown"
        help_text = _inspect(path, "exec", "--help") if cli == "codex" else _inspect(path, "--help")
        required = {"claude": ("--input-format", "--output-format", "--strict-mcp-config", "--tools"),
                    "codex": ("--json", "--sandbox", "--skip-git-repo-check"),
                    "gemini": ("--output-format", "--resume", "--allowed-mcp-server-names", "--policy",
                               "--skip-trust")}[cli]
        missing = [flag for flag in required if flag not in help_text]
        if missing:
            info["error"] = f"upgrade {cli}: this version lacks {', '.join(missing)}"
        else:
            info["supported"] = True
    except ProviderError as e:
        info["error"] = str(e)
    return info


def discover_clis() -> list[dict]:
    return [inspect_cli(cli) for cli in CLIS]


def proxy_command(url: str, token: str, cli: str) -> list[str]:
    prefix = [sys.executable] if getattr(sys, "frozen", False) else [
        sys.executable, "-m", "badshop.server"]
    return [*prefix, "mcp", "--connect", url, "--token", token, "--actor", f"cli:{cli}"]


def _parse_event(cli: str, event: dict) -> dict:
    """Normalize known events without discarding unknown JSON. Never execute tool events here."""
    kind = event.get("type", "unknown")
    result: dict = {"kind": "raw", "raw": event}
    if cli == "claude":
        if kind == "system" and event.get("session_id"):
            return {"kind": "session", "session_id": event["session_id"]}
        if kind == "stream_event":
            delta = (event.get("event") or {}).get("delta") or {}
            if delta.get("type") == "text_delta":
                return {"kind": "text", "text": delta.get("text", "")}
        if kind == "assistant":
            text = "".join(p.get("text", "") for p in (event.get("message") or {}).get("content", [])
                           if p.get("type") == "text")
            return {"kind": "snapshot", "text": text, "id": (event.get("message") or {}).get("id", "assistant")}
        if kind == "result":
            if event.get("is_error"):
                return {"kind": "error", "error": event.get("result") or "; ".join(event.get("errors", []))}
            return {"kind": "done", "text": event.get("result", ""),
                    "session_id": event.get("session_id")}
    elif cli == "codex":
        if kind == "thread.started":
            return {"kind": "session", "session_id": event.get("thread_id")}
        if kind in ("item.completed", "item.updated"):
            item = event.get("item") or {}
            if item.get("type") == "agent_message":
                return {"kind": "snapshot", "text": item.get("text", ""), "id": item.get("id", "")}
        if kind == "turn.completed":
            return {"kind": "done"}
        if kind in ("error", "turn.failed"):
            error = event.get("error") or event.get("message") or "Codex turn failed"
            return {"kind": "error", "error": error.get("message", str(error)) if isinstance(error, dict) else error}
    else:
        if kind == "init":
            return {"kind": "session", "session_id": event.get("session_id")}
        if kind == "message" and event.get("role") == "assistant":
            return {"kind": "text" if event.get("delta") else "snapshot", "text": event.get("content", "")}
        if kind == "result":
            if event.get("status") == "error":
                error = event.get("error") or {}
                return {"kind": "error", "error": error.get("message", str(error))}
            return {"kind": "done"}
        if kind == "error":
            return {"kind": "error", "error": event.get("message", "Gemini turn failed")}
    return result


def parse_event(cli: str, event: dict) -> dict:
    """CLI upgrades may change nested shapes as well as event names."""
    try:
        return _parse_event(cli, event)
    except (AttributeError, TypeError, KeyError):
        return {"kind": "raw", "raw": event, "parse_error": True}


class CLIProvider:
    """One private working directory and Claude process per app session/profile."""

    def __init__(self, profile: Profile, url: str, token: str):
        self.profile = profile
        self.cli = profile.cli
        self.actor = f"cli:{self.cli}"
        self.info = inspect_cli(self.cli, profile.executable)
        if not self.info["supported"]:
            raise ProviderError(self.info.get("error", "unsupported CLI"))
        self.executable = self.info["executable"]
        self._folder = tempfile.TemporaryDirectory(prefix="badshop-cli-")
        self.cwd = Path(self._folder.name)
        self.env = dict(os.environ)
        self.process = None
        self.session_id: str | None = None
        self._stderr_task: asyncio.Task | None = None
        self._exit_task: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._job = None
        self._stderr: deque[str] = deque(maxlen=40)
        try:
            self._base = self._configure(proxy_command(url, token, self.cli))
        except (OSError, ValueError, KeyError, TypeError) as e:
            self._folder.cleanup()
            raise ProviderError(f"{self.cli} could not be configured: {e}") from None
        except Exception:
            self._folder.cleanup()
            raise

    def check_capabilities(self) -> dict:
        return {"vision": True, "tool_calls": True, "experimental": self.cli == "gemini"}

    def _write(self, relative: str, value: str) -> Path:
        path = self.cwd / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(value, encoding="utf-8")
        path.chmod(0o600)
        return path

    def _configure(self, proxy: list[str]) -> list[str]:
        mcp = {"command": proxy[0], "args": proxy[1:]}
        if self.cli == "claude":
            self.env["CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT"] = "0"
            # The subscription's OAuth/keychain stays in the usual user config directory.
            return [self.executable, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                    "--verbose", "--include-partial-messages", "--strict-mcp-config", "--mcp-config",
                    json.dumps({"mcpServers": {"badshop": mcp}}), "--allowedTools", "mcp__badshop__*",
                    "--tools", "", "--setting-sources", "", "--system-prompt", SYSTEM_PROMPT,
                    *(["--model", self.profile.model] if self.profile.model else [])]
        if self.cli == "codex":
            # Keep the user's credentials via a link, never a credential copy or a global config write.
            user_dir = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
            private = self.cwd / "codex"
            private.mkdir(mode=0o700)
            if (user_dir / "auth.json").is_file():
                source = (user_dir / "auth.json").resolve()
                try:
                    (private / "auth.json").symlink_to(source)
                except OSError:
                    # Windows may prohibit symlinks without Developer Mode. A hard link also
                    # preserves the existing login without copying or overwriting credentials.
                    os.link(source, private / "auth.json")
            self.env["CODEX_HOME"] = str(private)
            # Built-in apply_patch is independently controlled by model metadata, not shell_tool.
            # Read the bundled, offline catalog and remove pixel/file bypass tools for every model.
            catalog = json.loads(_inspect(self.executable, "debug", "models", "--bundled"))
            for model in catalog["models"]:
                model.update(shell_type="disabled", apply_patch_tool_type=None, experimental_supported_tools=[],
                             supports_search_tool=False, tool_mode="direct", multi_agent_version=None)
            catalog_path = self._write("codex/models.json", json.dumps(catalog))
            config = ('sandbox_mode = "read-only"\napproval_policy = "never"\nweb_search = "disabled"\n'
                      f'model_catalog_json = {json.dumps(str(catalog_path))}\n'
                      '[tools.update_plan]\nenabled = false\n'
                      '[tools.experimental_request_user_input]\nenabled = false\n'
                      '[features]\nshell_tool = false\nview_image = false\nimage_generation = false\n'
                      'multi_agent = false\ncollab = false\napps = false\nplugins = false\n'
                      'code_mode = false\nrequest_permissions_tool = false\n'
                      '[mcp_servers.badshop]\n'
                      f'command = {json.dumps(mcp["command"])}\nargs = {json.dumps(mcp["args"])}\n'
                      'tool_timeout_sec = 3600\ndefault_tools_approval_mode = "approve"\n')
            self._write("codex/config.toml", config)
            self._write("AGENTS.md", SYSTEM_PROMPT)
            return [self.executable, "exec", "--json", "--skip-git-repo-check", "--ignore-rules",
                    *(["--model", self.profile.model] if self.profile.model else [])]
        settings = {"mcpServers": {"badshop": {**mcp, "trust": True, "timeout": 3600000}},
                    "mcp": {"allowed": ["badshop"]},
                    # tools.core's catch-all DENY also matches MCP and outranks server trust.
                    # The explicit server-scoped allow has higher priority than that DENY;
                    # every built-in and every other MCP server remains denied.
                    "tools": {"core": [], "allowed": ["mcp_badshop_*"]},
                    "hooksConfig": {"enabled": False}}
        # Modern Gemini rejects user-owned files masquerading as system settings. A
        # private CLI home loads only this config; link authentication, never user policy,
        # tool settings, extensions, skills or hooks from the real Gemini directory.
        user_gemini = Path(self.env.get("GEMINI_CLI_HOME", str(Path.home()))) / ".gemini"
        try:
            auth_type = json.loads((user_gemini / "settings.json").read_text(encoding="utf-8")) \
                .get("security", {}).get("auth", {}).get("selectedType")
        except (OSError, ValueError, AttributeError):
            auth_type = None
        if auth_type in ("oauth-personal", "gemini-api-key", "vertex-ai"):
            settings["security"] = {"auth": {"selectedType": auth_type}}
        self._write(".gemini/settings.json", json.dumps(settings))
        for filename in ("oauth_creds.json", "google_accounts.json"):
            source = user_gemini / filename
            if source.is_file():
                target = self.cwd / ".gemini" / filename
                try:
                    target.symlink_to(source.resolve())
                except OSError:
                    os.link(source, target)
        self.env["GEMINI_CLI_HOME"] = str(self.cwd)
        self.env["GEMINI_SYSTEM_MD"] = str(self._write("system.md", SYSTEM_PROMPT))
        # An explicit empty policy directory replaces ordinary user policy files,
        # whose high-priority tool allows could otherwise defeat the core deny rule.
        self._write("policies/.keep", "")
        return [self.executable, "--output-format", "stream-json", "--allowed-mcp-server-names", "badshop",
                "--policy", str(self.cwd / "policies"), "--skip-trust",
                *(["--model", self.profile.model] if self.profile.model else [])]

    def command(self, prompt: str) -> list[str]:
        if self.cli == "claude":
            return [*self._base, *(["--resume", self.session_id] if self.session_id else [])]
        if self.cli == "codex" and self.session_id:
            return [*self._base[:2], "resume", self.session_id, *self._base[2:], prompt]
        return [*self._base, *(["--resume", self.session_id] if self.session_id else []),
                *(["-p", prompt] if self.cli == "gemini" else [prompt])]

    async def _drain_stderr(self, process):
        while line := await process.stderr.readline():
            self._stderr.append(line.decode("utf-8", "replace").rstrip()[-2000:])

    async def _start(self, prompt: str):
        if self.process is not None:
            await self.stop()
        self._stderr.clear()
        launch = {"start_new_session": True}
        if os.name == "nt":
            from badshop.providers.windows_job import Job
            self._job = Job()
            launch = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000004}  # CREATE_SUSPENDED
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command(prompt), cwd=self.cwd, env=self.env,
                stdin=asyncio.subprocess.PIPE if self.cli == "claude" else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=MAX_LINE, **launch)
            if self._job:
                self._job.assign_and_resume(self.process.pid)
        except BaseException:
            await self.stop()
            raise
        self._stderr_task = asyncio.create_task(self._drain_stderr(self.process))
        self._exit_task = asyncio.create_task(self._watch_exit(self.process))

    async def _watch_exit(self, process):
        # Process.wait can wait for EOF on inherited pipes after the parent exited. The
        # returncode is updated independently, so stop remaining owned children promptly.
        while process.returncode is None:
            await asyncio.sleep(.05)
        if self._job:
            self._job.close()
            self._job = None
        elif os.name != "nt":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
                await asyncio.sleep(.25)
                os.killpg(process.pid, signal.SIGKILL)

    async def turn(self, prompt: str, on_delta: Callable[[str], None], on_event: Callable[[dict], None]) -> str:
        fragments: list[str] = []
        snapshots: dict[str, str] = {}
        streamed_since_snapshot = False
        done = False
        try:
            if self.process is None or self.process.returncode is not None or self.cli != "claude":
                await self._start(prompt)
            process = self.process
            if self.cli == "claude":
                message = {"type": "user", "message": {"role": "user", "content": prompt}}
                process.stdin.write((json.dumps(message) + "\n").encode())
                await process.stdin.drain()
            while line := await process.stdout.readline():
                raw = line.decode("utf-8", "replace").rstrip()
                try:
                    event = json.loads(raw)
                    if not isinstance(event, dict):
                        raise ValueError("expected an event object")
                except ValueError:
                    on_event({"kind": "raw", "raw": raw, "parse_error": True})
                    continue
                normalized = parse_event(self.cli, event)
                kind = normalized["kind"]
                if normalized.get("session_id"):
                    self.session_id = normalized["session_id"]
                if kind == "session":
                    continue
                if kind == "error":
                    raise ProviderError(str(normalized["error"]))
                if kind == "text":
                    chunk = normalized.get("text", "")
                    streamed_since_snapshot = True
                    fragments.append(chunk)
                    on_delta(chunk)
                elif kind == "snapshot":
                    key = normalized.get("id", "assistant")
                    text = normalized.get("text", "")
                    old = snapshots.get(key, "")
                    # Claude snapshots repeat the partial text stream; Codex snapshots grow per item.
                    if self.cli not in ("claude", "gemini") or not streamed_since_snapshot:
                        chunk = text[len(old):] if text.startswith(old) else text
                        fragments.append(chunk)
                        on_delta(chunk)
                    snapshots[key] = text
                    streamed_since_snapshot = False
                elif kind == "done":
                    if not fragments and normalized.get("text"):
                        fragments.append(normalized["text"])
                        on_delta(normalized["text"])
                    done = True
                    if self.cli == "claude":
                        break  # keep the process/stdin open for the next turn
                else:
                    on_event(normalized)
            if self.cli != "claude" or not done:
                code = await process.wait()
                try:
                    await asyncio.wait_for(asyncio.shield(self._stderr_task), .5)
                except TimeoutError:
                    await self.stop()
                if code or not done:
                    tail = "\n".join(self._stderr)
                    login = {"claude": "claude auth login", "codex": "codex login", "gemini": "gemini"}[self.cli]
                    raise ProviderError(f"{self.cli} exited ({code}) before completing the turn. "
                                        f"If login is needed, run `{login}` in a terminal.\n{tail}")
            return "".join(fragments)
        except asyncio.CancelledError:
            await self.stop()
            raise
        except (OSError, ValueError) as e:
            await self.stop()
            raise ProviderError(f"{self.cli} stream failed: {e}") from None
        except ProviderError:
            await self.stop()
            raise

    async def stop(self):
        # Repeated Stop/UI disconnect cancellation must not interrupt cleanup after
        # ownership has been removed from self.process.
        task = getattr(self, "_cleanup_task", None)
        if task is None or task.done():
            task = asyncio.create_task(self._stop_impl())
            self._cleanup_task = task
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def _stop_impl(self):
        process, self.process = self.process, None
        exit_task, self._exit_task = getattr(self, "_exit_task", None), None
        if exit_task:
            exit_task.cancel()
            await asyncio.gather(exit_task, return_exceptions=True)
        job, self._job = getattr(self, "_job", None), None
        if job:
            job.close()  # kills the whole Windows tree even if its original parent exited
        if process is not None:
            with contextlib.suppress(ProcessLookupError):
                if os.name != "nt":
                    # The group remains ours while descendants hold it, even after the leader exits.
                    os.killpg(process.pid, signal.SIGTERM)
                elif process.returncode is None:
                    process.terminate()
            try:
                await asyncio.wait_for(asyncio.shield(process.wait()), 3)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    elif process.returncode is None:
                        process.kill()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(process.wait(), 1)
            if os.name != "nt":
                # wait() may return immediately for an exited leader while a descendant
                # ignores SIGTERM. Escalate for the owned group in that case as well.
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
        if process is not None and process.stdin:
            process.stdin.close()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError, TimeoutError):
                await asyncio.wait_for(process.stdin.wait_closed(), .5)
        if self._stderr_task:
            try:
                await asyncio.wait_for(asyncio.shield(self._stderr_task), .5)
            except (TimeoutError, ValueError):
                self._stderr_task.cancel()
            await asyncio.gather(self._stderr_task, return_exceptions=True)
            self._stderr_task = None
        if process is not None:
            # asyncio offers no public close for subprocess pipe readers. After bounded cleanup,
            # close the transport so an escaped/inherited descriptor cannot retain the app forever.
            transport = getattr(process, "_transport", None)
            if transport:
                transport.close()

    async def close(self):
        await self.stop()
        self._folder.cleanup()
