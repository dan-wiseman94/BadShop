"""Install and own the optional on-device inference process."""

import asyncio
import hashlib
import os
import secrets
import socket
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import httpx

from badshop.agent.provider import ProviderError
from badshop.diagnostics import log_dir, register_secret
from badshop.engine import assets, manifest, vision_packages


def available() -> bool:
    required = manifest.vision_assets()
    return bool(required) and all(manifest.is_present(item) for item in required)


def _unpack(package: manifest.Asset, folder: Path) -> None:
    archive = manifest.asset_path(package)
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != package.sha256:
            raise ProviderError("An on-device AI download is damaged. Download it again in Settings.")
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as reader:
            for entry in reader.infolist():
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in entry.filename or ":" in entry.filename:
                    raise ProviderError("The on-device AI archive contains an invalid path.")
            reader.extractall(folder)
    else:
        with tarfile.open(archive) as reader:
            reader.extractall(folder, filter="data")


def _install() -> tuple[Path, list[Path]]:
    packages = manifest.vision_assets()[len(manifest.VISION_WEIGHTS):]
    if not available():
        raise ProviderError("Set up On-device AI in Settings → Assets before using it.")
    root = assets.data_dir() / "local-vision"
    libraries = []
    server = None
    binary = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    for package in packages:
        name = Path(package.name).name
        installed = root / (name + ".installed")
        if not installed.is_dir():
            with tempfile.TemporaryDirectory(dir=root, prefix="unpack-") as temp:
                staged = Path(temp) / "runtime"
                staged.mkdir()
                _unpack(package, staged)
                try:
                    staged.rename(installed)
                except OSError:
                    if not installed.is_dir():
                        raise
        if name.startswith("cudart-"):
            libraries.extend(path.parent for path in installed.rglob("libcudart.so.12"))
        else:
            server = next(installed.rglob(binary), None)
    if server is None:
        raise ProviderError("BadShop could not find the on-device AI runtime. Check Settings → Assets.")
    return server, libraries


class LocalVisionRuntime:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._process: subprocess.Popen | None = None
        self._job = None
        self._url = ""
        self._key = ""

    def _launch(self, server: Path, libraries: list[Path], port: int, gpu: bool) -> None:
        weights, projector = (str(manifest.asset_path(asset).resolve()) for asset in manifest.VISION_WEIGHTS)
        args = [str(server.resolve()), "--model", weights, "--mmproj", projector, "--alias", "badshop",
                "--host", "127.0.0.1", "--port", str(port), "--no-ui", "--jinja", "--parallel", "1",
                "--ctx-size", "16384", "--image-max-tokens", "1024", "--reasoning-budget", "0",
                "--n-gpu-layers", "99" if gpu else "0", "--threads", str(min(os.cpu_count() or 4, 8))]
        if not gpu:
            args.extend(["--device", "none", "--no-mmproj-offload"])
        elif vision_packages.selected()[0] == "linux-cuda":
            args.extend(["--device", "CUDA0"])
        env = {key: value for key, value in os.environ.items() if not key.startswith("LLAMA_")}
        env["LLAMA_API_KEY"] = self._key
        if sys.platform == "linux":
            original = env.get("LD_LIBRARY_PATH_ORIG" if getattr(sys, "frozen", False) else "LD_LIBRARY_PATH")
            paths = [str(path.resolve()) for path in [server.parent, *libraries]]
            if Path("/usr/lib/wsl/lib").is_dir():
                paths.append("/usr/lib/wsl/lib")
            env["LD_LIBRARY_PATH"] = os.pathsep.join(paths + ([original] if original else []))
        flags = 0
        if sys.platform == "win32":
            from badshop.providers.windows_job import Job
            self._job = Job()
            flags = subprocess.CREATE_NO_WINDOW | 0x00000004  # assign suspended child to the job
        folder = log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "on-device-ai.log").open("wb") as log:
            log.write(f"BadShop runtime: {vision_packages.selected()[0]}, {'GPU' if gpu else 'CPU'}\n".encode())
            log.flush()
            self._process = subprocess.Popen(args, env=env, cwd=server.parent, stdin=subprocess.DEVNULL,
                                             stdout=log, stderr=log, creationflags=flags)
        if self._job is not None:
            self._job.assign_and_resume(self._process.pid)

    async def _stop(self) -> None:
        process, self._process = self._process, None
        if self._job is not None:
            self._job.close()
            self._job = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 3)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)

    async def close(self) -> None:
        async with self._lock:
            await self._stop()

    async def endpoint(self) -> tuple[str, str]:
        async with httpx.AsyncClient(trust_env=False) as client:
            await self._ready(client)
        return self._url, self._key

    async def _ready(self, client: httpx.AsyncClient) -> None:
        async with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            await self._stop()
            try:
                server, libraries = await asyncio.to_thread(_install)
                accelerated = vision_packages.selected()[0] in {"linux-cuda", "win32-vulkan", "darwin-arm64"}
                for gpu in (True, False) if accelerated else (False,):
                    with socket.socket() as sock:
                        sock.bind(("127.0.0.1", 0))
                        port = sock.getsockname()[1]
                    self._url = f"http://127.0.0.1:{port}"
                    self._key = secrets.token_urlsafe(32)
                    register_secret(self._key)
                    self._launch(server, libraries, port, gpu)
                    for _ in range(240):
                        if self._process.poll() is not None:
                            break
                        try:
                            response = await client.get(self._url + "/health", timeout=0.5)
                            if response.is_success and response.json().get("status") == "ok":
                                return
                        except (httpx.HTTPError, ValueError):
                            pass
                        await asyncio.sleep(0.25)
                    await self._stop()
            except asyncio.CancelledError:
                await self._stop()
                raise
            except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile):
                await self._stop()
                raise ProviderError("BadShop could not prepare On-device AI. Check Settings → Assets.") from None
            raise ProviderError("On-device AI could not start. See on-device-ai.log in BadShop’s logs.")
