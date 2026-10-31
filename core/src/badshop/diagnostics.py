"""Private structured application logs and a bounded, shareable crash report.

Only the badshop logger is configured: SDK wire logs can contain prompts and keys.
Exception types are useful diagnostics; exception bodies/tracebacks are not recorded.
"""

import importlib.metadata
import json
import logging
import logging.handlers
import os
import platform
import re
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import platformdirs

from badshop import __version__

_REDACTED = "[redacted]"
_SECRETS: set[str] = set()
_LOCK = threading.RLock()
_SENSITIVE_KEY = re.compile(r"key|token|secret|password|credential|authorization|cookie|image|prompt|messages|transcript", re.I)
_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|authorization)\b[\"']?\s*[:=]\s*)"
    r"(?:Bearer\s+)?(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)")
_DATA = re.compile(r"data:[^\s,;]+(?:;[^\s,]+)*,[^\s\"']+", re.I)
_URL_USER = re.compile(r"(https?://)[^\s/@]+(?::[^\s/@]*)?@", re.I)
_URL_QUERY = re.compile(r"(https?://[^\s?\"'<>]+)\?[^\s\"'<>]+", re.I)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s\"',;}]+")
_KEY = re.compile(r"\b(?:sk|pk|AIza|ghp|github_pat)[-_][A-Za-z0-9_-]{8,}\b")


def register_secret(secret: str) -> None:
    """Register an in-memory profile credential, never persisted by this module."""
    if secret:
        with _LOCK:
            _SECRETS.add(secret)


def _text(value: str) -> str:
    with _LOCK:
        secrets = set(_SECRETS)
    # Read only likely credential values for redaction, never include the environment in a report.
    secrets.update(v for k, v in os.environ.items() if v and _SENSITIVE_KEY.search(k))
    for secret in sorted(secrets, key=len, reverse=True):
        value = value.replace(secret, _REDACTED)
    value = _DATA.sub(_REDACTED, value)
    value = _URL_USER.sub(r"\1[redacted]@", value)
    value = _URL_QUERY.sub(r"\1?[redacted]", value)
    value = _ASSIGNMENT.sub(lambda m: m[1] + _REDACTED, value)
    value = _BEARER.sub("Bearer " + _REDACTED, value)
    return _KEY.sub(_REDACTED, value)


def redact(value: Any) -> Any:
    """Copy JSON-like data while removing credentials, image bodies and request context."""
    if isinstance(value, dict):
        return {str(k): _REDACTED if _SENSITIVE_KEY.search(str(k)) else redact(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _text(value)
    if value is None or type(value) in (bool, int, float):
        return value
    return f"<{type(value).__name__}>"  # object's repr may contain a complete SDK request


class _PrivateRotatingHandler(logging.handlers.TimedRotatingFileHandler):
    def _open(self):
        # os.open's creation mode avoids a permissive window even after nightly rollover.
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.chmod(self.baseFilename, 0o600)
            return os.fdopen(fd, self.mode, encoding=self.encoding, errors=self.errors)
        except BaseException:
            os.close(fd)
            raise


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        try:
            message = record.getMessage()
        except Exception:
            message = "log message unavailable"
        event = {"time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                 "level": record.levelname, "logger": record.name, "message": _text(message)}
        if hasattr(record, "data"):
            event["data"] = redact(record.data)
        if record.exc_info and record.exc_info[0]:
            event["exception"] = record.exc_info[0].__name__
        return json.dumps(event, ensure_ascii=True)


def log_dir() -> Path:
    override = os.environ.get("BADSHOP_LOG_DIR")
    return Path(override) if override else Path(platformdirs.user_log_dir("badshop", appauthor=False))


def configure_logging(directory: Path | None = None) -> Path:
    """Set up badshop.log, rotated nightly with seven backups, without stdout output.

    Repeated startup replaces this module's handler only; callers' handlers are preserved.
    """
    directory = Path(directory) if directory is not None else log_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = (directory / "badshop.log").resolve()
    with _LOCK:
        logger = logging.getLogger("badshop")
        for handler in list(logger.handlers):
            if getattr(handler, "_badshop_diagnostics", False):
                logger.removeHandler(handler)
                handler.close()
        handler = _PrivateRotatingHandler(
            path, when="midnight", interval=1, backupCount=7, encoding="utf-8", utc=True)
        os.chmod(path, 0o600)
        handler._badshop_diagnostics = True
        handler.setFormatter(_JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return path


def _tail(path: Path) -> list[str]:
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            end = stream.tell()
            stream.seek(max(0, end - 1024 * 1024))
            if end > 1024 * 1024:
                stream.readline()  # a partial first line isn't a usable structured record
            return [_text(line) for line in deque(stream.read().decode("utf-8", "replace").splitlines(), maxlen=200)]
    except OSError:
        return []


def diagnostic_report(directory: Path | None = None) -> dict:
    """Versions, OS and at most the last 200 log lines, never credentials or settings."""
    directory = Path(directory) if directory is not None else log_dir()
    versions = {"badshop": __version__, "python": platform.python_version()}
    for package in ("Pillow", "numpy", "opencv-python-headless", "rembg", "onnxruntime", "litellm", "mcp"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not installed"
    path = directory / "badshop.log"
    lines = _tail(path)
    # A crash just after midnight can leave the current file almost empty.
    for previous in sorted(directory.glob("badshop.log.*"), reverse=True)[:7]:
        if len(lines) >= 200:
            break
        lines = (_tail(previous) + lines)[-200:]
    return {"versions": versions, "os": platform.platform(), "log_path": str(path), "log_lines": lines}
