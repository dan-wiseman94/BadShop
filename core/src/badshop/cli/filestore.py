"""Store implementation for the CLI: refs are file paths."""

import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from badshop.engine.common import load_image
from badshop.engine.errors import EngineError
from badshop.engine.result import Output


def final_path(final_dir: Path, stem: str, ext: str) -> Path:
    """Finished files never overwrite older ones: stem.ext, stem_2.ext, stem_3.ext..."""
    final_dir.mkdir(parents=True, exist_ok=True)
    p, i = final_dir / f"{stem}{ext}", 2
    while p.exists():
        p, i = final_dir / f"{stem}_{i}{ext}", i + 1
    return p


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
    def __init__(self, work_dir: Path, final_dir: Path, out: str | None = None):
        self.work_dir, self.final_dir, self.out = work_dir, final_dir, out
        self._count = 0

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
            with _writing(self.final_dir):
                path = final_path(self.final_dir, output.name_hint[6:].replace("{stem}", clean_stem(stem)), output.ext())
        else:
            path = self.work_dir / output.name_hint.replace("{stem}", stem)
        with _writing(path):
            path.parent.mkdir(parents=True, exist_ok=True)
            if self.out and first:
                _save_as_suffix(output, path)
            else:
                path.write_bytes(output.encode())
        return str(path)

    def export(self, ref: str, name: str | None) -> str:
        src = Path(ref)
        if not src.is_file():
            raise EngineError(f"no such image: {ref}", hint=PATH_HINT)
        with _writing(self.final_dir):
            dest = final_path(self.final_dir, name or clean_stem(src.stem), src.suffix)
        with _writing(dest):
            shutil.copyfile(src, dest)
        return str(dest)
