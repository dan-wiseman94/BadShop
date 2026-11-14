"""Immutable encoded blobs. Metadata may reference a blob only after publication."""

import hashlib
import re
import weakref
from pathlib import Path
from tempfile import TemporaryDirectory

from badshop.atomic import sync_directory, write_new_bytes
from badshop.engine.errors import EngineError

HASH = re.compile(r'[0-9a-f]{64}')


class BlobStore:
    def __init__(self, root: Path | None = None):
        self._temporary = TemporaryDirectory(prefix='badshop-blobs-') if root is None else None
        self.root = Path(self._temporary.name) if self._temporary else root
        created = not self.root.exists()
        self.root.mkdir(parents=True, exist_ok=True)
        if created:
            sync_directory(self.root.parent)
        if self._temporary is not None:
            self._cleanup = weakref.finalize(self, self._temporary.cleanup)

    def close(self):
        if self._temporary is not None:
            self._cleanup()

    def path(self, digest: str) -> Path:
        if not HASH.fullmatch(digest):
            raise EngineError('invalid blob identity')
        return self.root / digest

    def put(self, data: bytes) -> Path:
        digest = hashlib.sha256(data).hexdigest()
        path = self.path(digest)
        try:
            write_new_bytes(path, data)
        except FileExistsError:
            self.verify(path, digest)
        except OSError as error:
            raise EngineError('could not store image bytes', hint=str(error)) from None
        sync_directory(self.root)
        return path

    @staticmethod
    def verify(path: Path, digest: str) -> None:
        try:
            if path.is_symlink():
                raise EngineError('stored image is not an immutable blob')
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        except OSError as error:
            raise EngineError('stored image is missing or unreadable', hint=str(error)) from None
        if actual != digest:
            raise EngineError('stored image bytes failed integrity verification')

    @staticmethod
    def read(path: Path, digest: str) -> bytes:
        try:
            if path.is_symlink():
                raise EngineError('stored image is not an immutable blob')
            data = path.read_bytes()
        except OSError as error:
            raise EngineError('stored image is missing or unreadable', hint=str(error)) from None
        if hashlib.sha256(data).hexdigest() != digest:
            raise EngineError('stored image bytes failed integrity verification')
        return data
