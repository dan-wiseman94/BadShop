"""Source credentials in the OS keychain; the index contains names only."""

import json
import os
import uuid
from pathlib import Path
import platformdirs
from badshop.engine.errors import EngineError

SERVICE = "badshop.sources"
ENVS = {
    "flickr": "BADSHOP_FLICKR_API_KEY",
    "smithsonian": "BADSHOP_SMITHSONIAN_API_KEY",
    "bhl": "BADSHOP_BHL_API_KEY",
    "europeana": "BADSHOP_EUROPEANA_API_KEY",
    "pexels": "BADSHOP_PEXELS_API_KEY",
    "pixabay": "BADSHOP_PIXABAY_API_KEY",
    "brave": "BADSHOP_BRAVE_API_KEY",
}


def _path():
    return (
        Path(os.environ.get("BADSHOP_CONFIG_DIR") or platformdirs.user_config_dir("badshop", appauthor=False))
        / "source-keys.json"
    )


def saved():
    try:
        value = json.loads(_path().read_text(encoding="utf-8"))
        return [v for v in value if v in ENVS] if isinstance(value, list) else []
    except (OSError, ValueError):
        return []


def configured(env):
    return (
        bool(os.environ.get(env, "").strip())
        or next((s for s, e in ENVS.items() if e == env), None) in saved()
    )


def resolve(env):
    if value := os.environ.get(env, "").strip():
        return value
    source = next((s for s, e in ENVS.items() if e == env), None)
    if source not in saved():
        return None
    try:
        import keyring

        value = keyring.get_password(SERVICE, source)
    except Exception:
        raise EngineError(
            "source keychain is unavailable", hint=f"set {env} in the environment or unlock your keychain"
        ) from None
    if not value:
        raise EngineError("saved source key is missing", hint=f"save it again or set {env}")
    return value


def set_key(source, key):
    if source not in ENVS:
        raise EngineError("this source does not accept an API key")
    if len(key) > 4096:
        raise EngineError("API key is too long")
    import keyring

    try:
        if key:
            keyring.set_password(SERVICE, source, key)
        elif source in saved():
            keyring.delete_password(SERVICE, source)
    except Exception:
        raise EngineError(
            "could not update the source keychain", hint=f"unlock it or set {ENVS[source]} in the environment"
        ) from None
    ids = set(saved())
    ids.discard(source)
    if key:
        ids.add(source)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(json.dumps(sorted(ids)), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return {"saved": bool(key), "source": source}
