"""Every file badshop downloads on first use: the fonts, the face detector and the background removers.
The app lists them (assets.status), pre-downloads them (assets.download) and maps assets.PROGRESS
events back to them by name."""

from dataclasses import dataclass
from pathlib import Path

from badshop.engine import assets, faces, text
from badshop.engine.errors import EngineError


@dataclass(frozen=True)
class Asset:
    name: str  # exactly the name cached() is called with, so PROGRESS events map to assets
    label: str  # what Settings shows
    url: str
    approx_mb: int
    size: int | None = None
    sha256: str | None = None
    md5: str | None = None  # rembg pins its models by md5
    rembg_model: str | None = None  # set for rembg's models, which live where rembg looks for them


_ANTON = text.FONT_DOWNLOADS["Anton-Regular.ttf"]
_COMIC = text.FONT_DOWNLOADS["ComicNeue-Bold.ttf"]
# rembg's own release files, URLs and md5s as in rembg's session classes (a test compares them).
# Each is stored as <model>.onnx: birefnet-general comes from BiRefNet-general-epoch_244.onnx.
_REMBG = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/"

ASSETS: tuple[Asset, ...] = (
    Asset("fonts/Anton-Regular.ttf", "Anton font (an Impact lookalike)", _ANTON.url, 1,
          size=_ANTON.size, sha256=_ANTON.sha256),
    Asset("fonts/ComicNeue-Bold.ttf", "Comic Neue Bold font (a Comic Sans lookalike)", _COMIC.url, 1,
          size=_COMIC.size, sha256=_COMIC.sha256),
    Asset("face_detection_yunet_2023mar.onnx", "YuNet face finder", faces.YUNET.url, 1,
          size=faces.YUNET.size, sha256=faces.YUNET.sha256),
    Asset("rembg/u2net.onnx", "U2-Net background remover (the default)", _REMBG + "u2net.onnx", 168,
          size=175997641, md5="60024c5c889badc19c04ad937298a77b", rembg_model="u2net"),
    Asset("rembg/u2net_human_seg.onnx", "U2-Net background remover for people",
          _REMBG + "u2net_human_seg.onnx", 168,
          size=175997641, md5="c09ddc2e0104f800e3e1bb4652583d1f", rembg_model="u2net_human_seg"),
    Asset("rembg/isnet-anime.onnx", "IS-Net background remover for cartoons",
          _REMBG + "isnet-anime.onnx", 168,
          size=176069933, md5="6f184e756bb3bd901c8849220a83e38e", rembg_model="isnet-anime"),
    Asset("rembg/birefnet-general.onnx", "BiRefNet background remover (cleaner edges, large)",
          _REMBG + "BiRefNet-general-epoch_244.onnx", 928,
          size=972666916, md5="7a35a0141cbbc80de11d9c9a28f52697", rembg_model="birefnet-general"),
)


def get_asset(name: str) -> Asset:
    for a in ASSETS:
        if a.name == name:
            return a
    raise EngineError(f"unknown asset {name!r}", hint=f"assets: {', '.join(a.name for a in ASSETS)}")


def _session_class(model: str):
    """rembg's session class for `model`, found the way rembg.new_session finds it."""
    assets.configure_rembg()  # before rembg reads REMBG_HOME / U2NET_HOME
    from rembg.sessions import sessions_class

    for cls in sessions_class:
        if cls.name() == model:
            return cls
    raise EngineError(f"this rembg has no {model} model", hint="update rembg, or use another model")


def asset_path(a: Asset) -> Path:
    """Where the asset lives once downloaded. A rembg model goes where its session class looks first
    (<model_dir>/<model>.onnx), so rembg finds it and never downloads it itself."""
    if a.rembg_model is None:
        return assets.data_dir() / a.name
    return Path(_session_class(a.rembg_model).model_dir()) / f"{a.rembg_model}.onnx"


def is_present(a: Asset) -> bool:
    """True when cached() would not download it (the same test: a file of the pinned size)."""
    path = asset_path(a)
    return path.is_file() and (a.size is None or path.stat().st_size == a.size)


def status() -> list[dict]:
    return [{"name": a.name, "label": a.label, "approx_mb": a.approx_mb, "present": is_present(a)}
            for a in ASSETS]


def _fetch(a: Asset) -> Path:
    return assets.cached(a.name, a.url, sha256=a.sha256, size=a.size, md5=a.md5, dest=asset_path(a))


def download(name: str) -> Path:
    """Download one asset now (a cache hit when present); progress goes to assets.PROGRESS."""
    return _fetch(get_asset(name))


def ensure_rembg_model(model: str) -> Path:
    """rembg's weights for `model`, downloaded through cached() (progress, pinned size and md5) into the
    file rembg's session class opens, so rembg's own downloader (pooch) never runs or prints."""
    for a in ASSETS:
        if a.rembg_model == model:
            return _fetch(a)
    offered = ", ".join(a.rembg_model for a in ASSETS if a.rembg_model)
    raise EngineError(f"{model} is not a background remover badshop offers", hint=f"models: {offered}")
