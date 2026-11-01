"""Searchable indexes of explicitly chosen folders; agents never receive folder paths."""
import hashlib
import io
import json
import os
import time
import uuid
from pathlib import Path

from PIL import Image

from badshop.engine import assets
from badshop.engine.errors import EngineError
from badshop.session.media import IMAGE_FORMATS, data_url, persist_note, picked_path, small_image, source_bytes
from badshop.session.models import Source

EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}


class LocalCollections:
    def __init__(self, root=None):
        self.root = Path(root) if root else assets.data_dir() / "collections"

    def _path(self, id):
        if len(id) != 32 or any(c not in "0123456789abcdef" for c in id):
            raise EngineError("invalid collection id")
        return self.root / f"{id}.json"

    def _load(self, id):
        try:
            path = self._path(id)
            if path.stat().st_size > 64 * 2**20:
                raise EngineError("collection index is too large")
            return json.loads(path.read_text())
        except (OSError, ValueError):
            raise EngineError("collection index is missing or unreadable; index the folder again") from None

    def _write(self, record):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(record["id"])
        temp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            temp.write_text(json.dumps(record))
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def _summary(record):
        return {key: record[key] for key in ("id", "name", "count", "duplicates", "warnings")}

    def list(self):
        return [self._summary(self._load(p.stem)) for p in sorted(self.root.glob("*.json"))]

    def index(self, path: str, max_files=500):
        folder = picked_path(path, directory=True)
        if folder == Path(folder.anchor):
            raise EngineError("choose a specific picture folder, not a filesystem root")
        if not 1 <= max_files <= 2000:
            raise EngineError("index between 1 and 2000 images at once")
        id = hashlib.sha256(str(folder).encode()).hexdigest()[:32]
        previous = self._load(id) if self._path(id).exists() else {"entries": []}
        old = {e["id"]: e for e in previous["entries"]}
        entries, warnings, seen = [], [], {}
        inspected, total_bytes, encoded_bytes, started, stop = 0, 0, 0, time.monotonic(), False
        visited = 0
        for current, dirs, files in os.walk(folder, followlinks=False):
            visited += 1
            if visited > 1000 or time.monotonic() - started > 30:
                warnings.append("Folder traversal limit reached; choose a smaller picture folder.")
                break
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(current) / d).is_symlink())
            for name in sorted(files):
                inspected += 1
                if inspected > 10000 or len(entries) >= max_files or total_bytes >= 512 * 2**20 or time.monotonic() - started > 30:
                    warnings.append("Index limit reached; choose a smaller folder to include more images.")
                    stop = True
                    break
                candidate = Path(current) / name
                if name.startswith(".") or candidate.suffix.lower() not in EXTENSIONS or candidate.is_symlink():
                    continue
                try:
                    resolved = candidate.resolve(strict=True)
                    relative = str(resolved.relative_to(folder))
                    raw = source_bytes(resolved)
                    total_bytes += len(raw)
                    sha = hashlib.sha256(raw).hexdigest()
                    with Image.open(io.BytesIO(raw), formats=IMAGE_FORMATS) as image:
                        preview = small_image(image)
                        width, height = image.size
                    thumbnail = data_url(preview, 160)
                    encoded_bytes += len(thumbnail)
                    if encoded_bytes > 32 * 2**20:
                        warnings.append("Thumbnail index limit reached; choose a smaller folder.")
                        stop = True
                        break
                    entry_id = hashlib.sha256(relative.encode()).hexdigest()[:32]
                    old_entry = old.get(entry_id, {})
                    if old_entry.get("sha256") != sha:
                        old_entry = {}
                    entry = {"id": entry_id, "name": name, "relative": relative, "sha256": sha,
                             "tags": old_entry.get("tags", []), "description": old_entry.get("description", ""),
                             "width": width, "height": height, "thumbnail_data_url": thumbnail,
                             "duplicate_of": seen.get(sha)}
                    entries.append(entry)
                    seen.setdefault(sha, entry_id)
                except (OSError, ValueError, EngineError, Image.DecompressionBombError):
                    if len(warnings) < 20:
                        warnings.append(f"Skipped unreadable or oversized image: {name[:120]}")
            if stop:
                break
        record = {"id": id, "name": folder.name, "root": str(folder), "count": len(entries),
                  "duplicates": sum(e["duplicate_of"] is not None for e in entries),
                  "warnings": warnings, "entries": entries}
        self._write(record)
        return self._summary(record)

    def search(self, id, query="", limit=50):
        if not 1 <= limit <= 100:
            raise EngineError("result limit must be between 1 and 100")
        words = query.casefold().split()
        entries = self._load(id)["entries"]
        found = [e for e in entries if all(w in " ".join([e["name"], e["description"], *e["tags"]]).casefold()
                                           for w in words)]
        return [{k: v for k, v in e.items() if k not in ("relative", "sha256")} for e in found[:limit]]

    def update(self, collection_id, id, tags=None, description=None):
        record = self._load(collection_id)
        entry = next((e for e in record["entries"] if e["id"] == id), None)
        if entry is None:
            raise EngineError("no such indexed image")
        if tags is not None:
            if len(tags) > 50 or any(len(tag) > 80 for tag in tags):
                raise EngineError("use at most 50 tags of 80 characters")
            entry["tags"] = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
        if description is not None:
            if len(description) > 4096:
                raise EngineError("description is too long")
            entry["description"] = description.strip()
        self._write(record)
        return {k: v for k, v in entry.items() if k not in ("relative", "sha256")}

    def restore(self, session, collection_id, id):
        record = self._load(collection_id)
        entry = next((e for e in record["entries"] if e["id"] == id), None)
        if entry is None:
            raise EngineError("no such indexed image")
        root = picked_path(record["root"], directory=True)
        path = root / entry["relative"]
        try:
            # Reject newly introduced links, including symlink ancestors inside the chosen folder.
            if path.is_symlink() or path.resolve(strict=True) != path or not path.is_file():
                raise ValueError()
            path.relative_to(root)
        except (OSError, ValueError):
            raise EngineError("indexed file moved or became a link; index the folder again") from None
        raw = source_bytes(path)
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise EngineError("indexed image changed; index the folder again before importing")
        working = session.import_image(raw, entry["name"], Source(kind="local-collection", title=entry["name"]))
        original = session.artifacts.meta.get(working.original_id or "", working)
        persist_note(session, f"Imported {entry['name']} from selected collection", {
            "name": entry["name"], "sha256": entry["sha256"], "tags": entry["tags"],
            "description": entry["description"], "collection": record["name"]}, [working.id])
        return {"working": working.model_dump(mode="json"), "original": original.model_dump(mode="json")}

    def remove(self, id):
        self._load(id)
        self._path(id).unlink()
        return {"removed": True}
