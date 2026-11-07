"""Pinned upstream runtime downloads for the optional on-device provider."""

import os
import platform
import sys
from functools import cache
from pathlib import Path

RELEASE = "b12189"
BASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/"

# (filename, bytes, release asset SHA-256)
PACKAGES = {
    "linux-x64": ("llama-b12189-bin-ubuntu-x64.tar.gz", 23058620,
                  "c446a7ba4df3c3b1cc880a734fbff586d6d34b9cebc09e151754813b94ded8c9"),
    "linux-arm64": ("llama-b12189-bin-ubuntu-arm64.tar.gz", 18732824,
                    "30441cf9f5d9ce1b511c85dc2f6e494db6ba18c23da39013ab35f65b54f7267f"),
    "linux-cuda": ("llama-b12189-bin-ubuntu-cuda-12.8-x64.tar.gz", 188173082,
                   "664f720005135f621960b8f1550979a1bdd73b8ba887e2a47a314b0154fcaa0a"),
    "cuda-libraries": ("cudart-llama-b12189-bin-ubuntu-cuda-12.8-x64.tar.gz", 594371476,
                       "81408740817d383bd18b9f2f8d4fda14bbd1cf9dac63331e7b56c6fb82380650"),
    "win32-x64": ("llama-b12189-bin-win-cpu-x64.zip", 24749596,
                  "f912ea5e3e397c63405c81e732131ab0fa6e72411c80546bb5ad643f7dd82aac"),
    "win32-arm64": ("llama-b12189-bin-win-cpu-arm64.zip", 13227910,
                    "bdad32fd7d8b1fe700a1bb732d62eadb1529304af835c30a660da7b03d262cb8"),
    "win32-vulkan": ("llama-b12189-bin-win-vulkan-x64.zip", 37706485,
                     "9d56405579492423833cdde94cf46cae15d38333f585f3957cafebfc6fb0e182"),
    "darwin-arm64": ("llama-b12189-bin-macos-arm64.tar.gz", 16700174,
                     "f30e2f3032df30a0c37c9fbd43125253dcd4cb96d6a879aa81e464944bc20aee"),
    "darwin-x64": ("llama-b12189-bin-macos-x64.tar.gz", 12438130,
                   "c690cb11be36a910df7e3d5baf22ed2fb53c02243c72cd33aae8f5fd6c6afe55"),
}


@cache
def selected() -> tuple[str, ...]:
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if sys.platform == "linux":
        libc, version = platform.libc_ver()
        parts = version.split(".")[:2]
        if libc != "glibc" or len(parts) != 2 or not all(part.isdecimal() for part in parts):
            return ()
        if tuple(map(int, parts)) < (2, 38):
            return ()
    if sys.platform == "linux" and arch == "x64":
        nvidia = Path("/dev/nvidiactl").exists()
        wsl_cuda = Path("/dev/dxg").exists() and Path("/usr/lib/wsl/lib/libcuda.so.1").is_file()
        if nvidia or wsl_cuda:
            return ("linux-cuda", "cuda-libraries")
    if sys.platform == "win32" and arch == "x64":
        if (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "vulkan-1.dll").is_file():
            return ("win32-vulkan",)
    key = f"{sys.platform}-{arch}"
    return (key,) if key in PACKAGES else ()
