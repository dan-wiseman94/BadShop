"""Store implementation for the CLI: refs are file paths."""

import os
import re
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from badshop.engine.common import load_image
from badshop.engine.errors import EngineError
from badshop.engine.result import Output
from badshop.files import final_path  # moved to badshop.files (sessions use it too); still importable here


def clean_stem(stem: str) -> str:
    return re.sub(r"_(work|result)$", "", stem)


PATH_HINT = "check the path; outputs are printed as `key: path` lines"


@contextmanager
def _writing(path: Path) -> Iterator[None]:
    """A filesystem failure (a file where a folder should be, no permission...) becomes a clean error."""
    try:
        yield
    except OSError as e:
        raise EngineError(f"can't write {path} ({e})", hint="check the folder exists and is writable") from None


def _save_as_suffix(output: Output, path: Path) -> None:
    """Write the -o output the way the reference's `im.save(out)` does: format from the suffix."""
    try:
        if output.frames:  # the reference's animate: PIL picks GIF, APNG or WebP from the suffix
            output.frames[0].save(path, save_all=True, append_images=output.frames[1:],
                                  duration=output.duration, loop=0, optimize=False)
        elif output.quality is not None:  # JPEG at a set quality; the reference forces JPEG too
            path.write_bytes(output.encode())
        else:
            output.image.save(path)
    except (ValueError, OSError, KeyError) as e:
        if isinstance(e, OSError) and e.errno is not None:
            raise  # a filesystem failure, not a format PIL can't write: _writing() reports it
        raise EngineError(f"can't write {path.name} ({e})",
                          hint="use a .png name (PNG keeps transparency)") from None


class FileStore:
    def __init__(self, work_dir: Path, final_dir: Path, out: str | None = None, *,
                 output_root: Path | None = None):
        self.work_dir, self.final_dir, self.out = work_dir, final_dir, out
        self.output_root = output_root
        self._count = 0
        self._written: set[Path] = set()  # one store serves one run

    def _unused(self, path: Path) -> Path:
        """One run never writes two outputs to the same path (emoji a b c -o e.png gives every output the key
        "emoji"): the later ones become x_2.png, x_3.png..."""
        p, i = path, 2
        while p in self._written:
            p, i = path.with_name(f"{path.stem}_{i}{path.suffix}"), i + 1
        self._written.add(p)
        return p

    def _destination(self, path: Path) -> Path:
        if self.output_root is None:
            return path
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError) as error:
            raise EngineError(f"can't resolve recipe output {path}: {error}") from None
        if not resolved.is_relative_to(self.output_root):
            raise EngineError(f"recipe writes outside this folder: {path}",
                              hint="if you trust this recipe, run it with --allow-outside")
        return resolved

    @contextmanager
    def _output_file(self, path: Path) -> Iterator[Path]:
        destination = self._destination(path)
        with _writing(destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            if self.output_root is None:
                yield destination
                return
            # Preserve the requested format and replace the local inode instead of
            # truncating an existing inode that could also be linked outside the recipe.
            fd, name = tempfile.mkstemp(prefix=".badshop-", suffix=path.suffix, dir=destination.parent)
            temporary = Path(name)
            try:
                os.close(fd)
                yield temporary
                if destination.exists():
                    temporary.chmod(stat.S_IMODE(destination.stat().st_mode))
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)

    def load(self, ref: str) -> Image.Image:
        path = Path(ref)
        if not path.is_file():
            raise EngineError(f"no such image: {ref}", hint=PATH_HINT)
        try:
            return load_image(path)
        except (UnidentifiedImageError, OSError) as e:
            raise EngineError(f"{ref} isn't an image this tool can read ({e})",
                              hint="use a PNG, JPEG, GIF or WebP file") from None
        except Image.DecompressionBombError as e:  # not an OSError: Pillow refuses ~179+ megapixels
            raise EngineError(f"{ref} is too big to open ({e})", hint="use a smaller copy of the image") from None

    def put(self, output: Output, stem: str) -> str:
        first = self._count == 0
        self._count += 1
        if self.out and first:
            path = Path(self.out)
        elif self.out:  # secondary outputs sit next to -o: small.png -> small_grid.png
            o = Path(self.out)
            path = o.with_name(f"{o.stem}_{output.key}{output.ext()}")
        elif output.name_hint.startswith("final:"):
            directory = self._destination(self.final_dir)
            with _writing(directory):
                path = final_path(directory, output.name_hint[6:].replace("{stem}", clean_stem(stem)), output.ext())
            path = self.final_dir / path.name
        else:
            path = self.work_dir / output.name_hint.replace("{stem}", stem)
        path = self._unused(path)
        with self._output_file(path) as destination:
            if self.out and first:
                _save_as_suffix(output, destination)
            else:
                destination.write_bytes(output.encode())
        return str(path)

    def export(self, ref: str, name: str | None) -> str:
        src = Path(ref)
        self.load(ref).close()  # only images are exported: anything else is the load's clean error
        directory = self._destination(self.final_dir)
        with _writing(directory):
            dest = final_path(directory, name or clean_stem(src.stem), src.suffix)
        path = self.final_dir / dest.name
        with self._output_file(path) as target:
            shutil.copyfile(src, target)
        return str(path)
