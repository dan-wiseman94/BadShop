"""Project files (.badshop), the CLI recipe inside them, and the autosave.

A project is a zip: `session.json` (the SessionData, `"schema": 1`), `artifacts/<sha256><ext>` for every
artifact the session references, and `recipe.json` (the finished edits as a `badshop run` recipe). A
project may come from anywhere, so opening one trusts nothing in it: member names are never used as paths,
only the two compression methods badshop writes are accepted, sizes are checked before anything is read
and members are read a chunk at a time, every artifact must hash to its id and decode as an image, and
every failure is an EngineError. save refuses a project over the same size limits, so badshop never
writes a file it would then refuse to open.
"""

import contextlib
import hashlib
import json
import os
import re
import secrets
import stat
import struct
import time
import zipfile
import zlib
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from badshop.cli.argparse_gen import to_argv
from badshop.engine import assets
from badshop.engine.errors import EngineError
from badshop.session.artifacts import ArtifactStore, short
from badshop.session.models import SCHEMA, ArtifactMeta, SessionData, StepError
from badshop.session.session import Session, result_text
from badshop.tools import runner
from badshop.tools.registry import REGISTRY, image_fields

EXT = ".badshop"
SESSION_JSON = "session.json"
RECIPE_JSON = "recipe.json"
ARTIFACT_MEMBER = re.compile(r"^artifacts/([0-9a-f]{64})\.[a-z]{3,4}$")
ARTIFACT_ID = re.compile(r"^[0-9a-f]{64}$")
# The ids Session._next_id makes (s1, s2... and m1, m2...: ASCII digits, no leading zero). It reads every
# step and message id a session names, and int() fails on some others ("s²", thousands of digits). Nine
# digits is far past any real session. Matched with fullmatch, so a trailing new line is refused too.
STEP_ID = re.compile(r"s[1-9][0-9]{0,8}")
MESSAGE_ID = re.compile(r"m[1-9][0-9]{0,8}")
# Size limits, uncompressed, shared by save and open_project. session.json has its own, smaller one:
# json.loads and pydantic turn 16 MB of the worst-shaped JSON into about 1 GB of objects.
MAX_SESSION_BYTES = 16 * 2**20
MAX_MEMBER_BYTES = 512 * 2**20  # one artifact
MAX_PROJECT_BYTES = 2 * 2**30  # session.json and every artifact together
READ_CHUNK = 2**20
# The only compression methods badshop writes. zipfile inflates BZIP2 and LZMA members with no output
# limit at all, so a few KB of them can become gigabytes before any size check sees a byte.
METHODS = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
DAMAGED_HINT = "it may have been cut short or changed by something else; open another copy"
TOO_BIG_HINT = ("export the pictures you want to keep and start a new session for more; large imported "
                "originals (uncompressed BMP or TIFF files) take the most room")
# A step saved while it waited for approval or ran has no turn or tool left to finish it after a reopen.
# One nobody approved is rejected, as a stopped turn rejects what waits (ApprovalGate.cancel_all), so no
# replay ever runs it; one that was approved or running failed.
UNAPPROVED_TEXT = "rejected: badshop closed before it was approved"
INTERRUPTED = ("approved", "running")
INTERRUPTED_ERROR = StepError(message="badshop closed before this step finished",
                              hint="replay the step to run it again")

# What zipfile and zlib raise on a damaged archive (JSON and pydantic errors are handled first).
_ZIP_ERRORS = (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, ValueError, RuntimeError,
               NotImplementedError, struct.error, zlib.error)


def _member(meta: ArtifactMeta) -> str:
    return f"artifacts/{meta.id}{meta.ext}"


def _mb(n: int) -> str:
    return f"{n / 2**20:,.1f} MB"


def _size_problem(session_bytes: int, artifact_bytes: dict[str, int]) -> str | None:
    """Why a project whose members have these uncompressed sizes is too big to open, or None."""
    if session_bytes > MAX_SESSION_BYTES:
        return f"session.json is {_mb(session_bytes)}, over the {_mb(MAX_SESSION_BYTES)} limit"
    for aid, size in artifact_bytes.items():
        if size > MAX_MEMBER_BYTES:
            return f"artifact {short(aid)} is {_mb(size)}, over the {_mb(MAX_MEMBER_BYTES)} limit"
    total = session_bytes + sum(artifact_bytes.values())
    if total > MAX_PROJECT_BYTES:
        return f"{_mb(total)} in all, over the {_mb(MAX_PROJECT_BYTES)} limit"
    return None


def export_recipe(session: Session) -> dict:
    """The session's finished edits as a CLI recipe, `{"vars": {}, "steps": [argv, ...]}`.

    Only done steps of tools that make images locally are included (not read-only looks, not network
    sources, not export). Image refs become `artifacts/<id><ext>` and each step writes its first output to
    `-o artifacts/<id><ext>`, so `badshop run recipe.json` inside an unzipped project rebuilds them."""

    def path_of(aid: str) -> str:
        meta = session.artifacts.meta.get(aid)
        if meta is None:
            raise EngineError(f"artifact {short(aid)} is missing from the session",
                              hint="this is a bug in badshop; export the images you want to keep")
        return _member(meta)

    steps = []
    for step in session.data.steps:
        spec = REGISTRY.get(step.tool)
        if step.status != "done" or spec is None or not spec.mutates or spec.network or spec.writes_files:
            continue
        params = dict(step.params)
        for name, is_list in image_fields(spec.params).items():
            value = params.get(name)
            if value:
                params[name] = [path_of(v) for v in value] if is_list else path_of(value)
        argv = to_argv(spec, params)
        if step.outputs:  # before any "--": after it, "-o" would be read as a positional value
            at = argv.index("--") if "--" in argv else len(argv)
            argv[at:at] = ["-o", path_of(step.outputs[0])]
        steps.append(argv)
    return {"vars": {}, "steps": steps}


def save(session: Session, path: Path) -> Path:
    """Write the session to `path` (".badshop" is added when missing) and return the path written.

    Only the artifacts the session references are stored. The zip is written to a new temporary file in
    the same folder and moved over `path` in one step, so a crash mid-save leaves the previous file whole.
    The file gets the mode any saved file gets (the umask decides), or keeps the mode of the file it
    replaces. A project over open_project's size limits is refused before anything is written."""
    path = Path(path)
    if path.suffix.lower() != EXT:
        path = path.with_name(path.name + EXT)
    keep = sorted(session.referenced_ids())
    missing = [aid for aid in keep if aid not in session.artifacts]
    if missing:
        raise EngineError(f"can't save: artifact {short(missing[0])} is missing from the session",
                          hint="this is a bug in badshop; export the images you want to keep")
    payload = session.data.model_dump(mode="json", by_alias=True)
    payload["artifacts"] = {aid: session.artifacts.meta[aid].model_dump(mode="json", by_alias=True)
                            for aid in keep}
    # Plain ASCII JSON: a lone surrogate (which a JSON client can send in any text) is written as an
    # escape and read back unchanged, where UTF-8 could not encode it at all.
    session_json = json.dumps(payload, indent=1).encode("ascii")
    recipe_json = (json.dumps(export_recipe(session), indent=2) + "\n").encode("ascii")
    problem = _size_problem(len(session_json), {aid: len(session.artifacts.data(aid)) for aid in keep})
    if problem:
        raise EngineError(f"can't save {path.name}: the project would be too big to open again ({problem})",
                          hint=TOO_BIG_HINT)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.part")
    created = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # "x" makes a new file the way any saved file is made, so the umask sets its mode (mkstemp's 0600
        # would stay on the project after os.replace). An existing project keeps its own mode.
        with open(tmp, "xb") as fh:
            created = True
            with zipfile.ZipFile(fh, "w") as zf:
                zf.writestr(SESSION_JSON, session_json, zipfile.ZIP_DEFLATED)
                zf.writestr(RECIPE_JSON, recipe_json, zipfile.ZIP_DEFLATED)
                for aid in keep:  # PNG, JPEG and GIF are compressed already: store them as they are
                    zf.writestr(_member(session.artifacts.meta[aid]), session.artifacts.data(aid))
            fh.flush()
            os.fsync(fh.fileno())
        with contextlib.suppress(FileNotFoundError):
            os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
        os.replace(tmp, path)
    except BaseException as e:
        if created:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
        if isinstance(e, OSError):
            raise EngineError(f"can't save {path} ({e})", hint="check the folder exists and is writable, "
                              "and the disk isn't full") from None
        raise
    return path


def _damaged(path: Path, what: str, hint: str = DAMAGED_HINT) -> EngineError:
    return EngineError(f"{path.name} is damaged: {what}", hint=hint)


def _too_big(path: Path, what: str) -> EngineError:
    return EngineError(f"{path.name} is too big to open ({what})",
                       hint="badshop never saves a project this big, so something else changed or made it; "
                            "open another copy")


def _unsafe(name: str) -> bool:
    """A member name that would land outside a folder if anything ever extracted it."""
    return (name.startswith("/") or "\\" in name or bool(re.match(r"[A-Za-z]:", name))
            or ".." in PurePosixPath(name).parts)


def _index(path: Path, zf: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """Artifact id -> member. Refuses names that could climb out of a folder and compression methods
    badshop never writes (every member, read or not)."""
    found: dict[str, zipfile.ZipInfo] = {}
    for info in zf.infolist():
        if _unsafe(info.filename):
            raise EngineError(f"{path.name} isn't a safe badshop project: it holds a file named "
                              f"{info.filename!r}",
                              hint="badshop never writes names like that; don't open this file")
        if info.compress_type not in METHODS:
            raise EngineError(f"{path.name} isn't a badshop project: {info.filename!r} is compressed in a "
                              "way badshop never writes", hint="open a .badshop file saved by badshop")
        m = ARTIFACT_MEMBER.match(info.filename)
        if m:
            if m[1] in found:
                raise _damaged(path, f"artifact {short(m[1])} is stored twice")
            found[m[1]] = info
    return found


def _read(path: Path, zf: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int) -> bytes:
    """A member's bytes, never more than `cap` of them in memory.

    The declared size is checked first, but it can lie: zipfile cuts a member down to its declared size
    (then fails its CRC) only after inflating, and one read() of a DEFLATE member may inflate up to 2 GiB.
    Reading a chunk at a time keeps every inflate step small, and the running total is checked as it
    grows, so this holds whatever the headers say."""
    if info.file_size > cap:
        raise _too_big(path, f"{info.filename} is {_mb(info.file_size)}, over the {_mb(cap)} limit")
    chunks: list[bytes] = []
    total = 0
    with zf.open(info) as fh:
        while chunk := fh.read(READ_CHUNK):
            total += len(chunk)
            if total > cap:
                raise _too_big(path, f"{info.filename} holds more than {_mb(cap)}")
            chunks.append(chunk)
    return b"".join(chunks)


def _session_data(path: Path, raw: bytes) -> SessionData:
    try:
        payload = json.loads(raw)
    except ValueError as e:  # UnicodeDecodeError is a ValueError too
        raise _damaged(path, f"session.json isn't JSON ({e})") from None
    schema = payload.get("schema") if isinstance(payload, dict) else None
    if type(schema) is not int or schema < 1:
        raise _damaged(path, "session.json has no schema number")
    if schema > SCHEMA:
        raise EngineError(f"{path.name} was saved by a newer badshop (project schema {schema}; "
                          f"this badshop reads schema {SCHEMA})", hint="update badshop to open it")
    try:
        data = SessionData.model_validate(payload)
    except ValidationError as e:
        raise _damaged(path, "session.json isn't a badshop session", hint=runner.explain(e)) from None
    for step in data.steps:
        if step.tool not in REGISTRY:
            raise _damaged(path, f"step {step.index} uses a tool this badshop doesn't have ({step.tool})",
                           hint="update badshop to open it")
        try:  # stored params were validated when the step was made; anything else was changed since
            runner.validate(step.tool, step.params)
        except EngineError as e:
            raise _damaged(path, f"step {step.index} ({step.tool}) has bad parameters", hint=e.hint) from None
    for aid, meta in data.artifacts.items():
        if not ARTIFACT_ID.match(aid) or meta.id != aid:
            raise _damaged(path, f"artifact {aid[:16]!r} is listed under the wrong id")
    # every id Session._next_id reads: an odd one would make each later propose() or add_message() fail
    named = [(f"step {step.index} has", step.id, STEP_ID) for step in data.steps]
    for n, message in enumerate(data.messages, 1):
        named.append((f"message {n} has", message.id, MESSAGE_ID))
        named += [(f"message {n} names a step by", sid, STEP_ID) for sid in message.step_ids]
    named += [(f"artifact {short(aid)} names its step by", meta.produced_by, STEP_ID)
              for aid, meta in data.artifacts.items() if meta.produced_by is not None]
    for what, name, pattern in named:
        if not pattern.fullmatch(name):
            raise _damaged(path, f"{what} an id badshop never makes ({name[:16]!r})")
    return data


def _finish_interrupted(data: SessionData, artifacts: ArtifactStore) -> None:
    """Steps saved while waiting for approval or running (an autosave taken mid-turn): nothing can finish
    them after a reopen, because the turn and the worker are gone."""
    now = time.time()
    for step in data.steps:
        if step.status == "proposed":
            step.status, step.finished_at, step.result_text = "rejected", now, UNAPPROVED_TEXT
        elif step.status in INTERRUPTED:
            step.status, step.finished_at = "error", now
            step.error = INTERRUPTED_ERROR.model_copy()
            step.result_text = result_text(step, artifacts)


def open_project(path: Path, **session_kw) -> Session:
    """Open a project as a new Session (`session_kw` go to Session: executor, emit, output_dir, on_change).

    Reads only session.json and the listed `artifacts/<sha256><ext>` members, a chunk at a time and within
    the size limits. Checks the schema (a newer one is refused), every step's tool and params, that every
    step and message id is one badshop makes, every artifact's hash and that it decodes as an image badshop
    imports, and that every artifact the session references is present. A step saved while waiting for
    approval comes back rejected; one saved while approved or running comes back failed. Every failure is
    an EngineError; nothing outside the returned Session changes."""
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as zf:
            members = _index(path, zf)
            try:
                info = zf.getinfo(SESSION_JSON)
            except KeyError:
                raise EngineError(f"{path.name} isn't a badshop project (it has no session.json)",
                                  hint="open a .badshop file saved by badshop") from None
            data = _session_data(path, _read(path, zf, info, MAX_SESSION_BYTES))
            missing = [aid for aid in data.artifacts if aid not in members]
            if missing:
                raise _damaged(path, f"artifact {short(missing[0])} is missing")
            problem = _size_problem(info.file_size, {aid: members[aid].file_size for aid in data.artifacts})
            if problem:
                raise _too_big(path, problem)
            artifacts = ArtifactStore()
            for aid, meta in data.artifacts.items():
                blob = _read(path, zf, members[aid], MAX_MEMBER_BYTES)
                if hashlib.sha256(blob).hexdigest() != aid:
                    raise _damaged(path, f"artifact {short(aid)} doesn't match its id")
                try:  # decodes through the import formats only (never EPS), within MAX_IMPORT_PIXELS
                    artifacts.add(blob, meta.label, produced_by=meta.produced_by, source=meta.source,
                                  original_id=meta.original_id)
                except EngineError as e:
                    raise _damaged(path, f"artifact {short(aid)} can't be opened: {e.message}") from None
    except EngineError:
        raise
    except (FileNotFoundError, IsADirectoryError, PermissionError) as e:
        raise EngineError(f"can't open {path} ({e.strerror or e})", hint="check the path") from None
    except _ZIP_ERRORS as e:
        raise EngineError(f"{path.name} isn't a badshop project, or it is damaged ({type(e).__name__}: {e})",
                          hint="open a .badshop file saved by badshop; " + DAMAGED_HINT) from None
    _finish_interrupted(data, artifacts)
    session = Session(data, artifacts, **session_kw)  # Session makes data.artifacts the store's metas
    missing = session.referenced_ids() - set(artifacts.ids())
    if missing:
        raise _damaged(path, f"artifact {short(min(missing))} is missing")
    return session


def autosave_path() -> Path:
    """Where the open session is saved after every change (spec §9)."""
    return assets.data_dir() / "autosave" / f"session{EXT}"


def autosave(session: Session) -> None:
    """Save the open session to the data dir (spec §9); raises EngineError like save."""
    save(session, autosave_path())


def find_autosave() -> Path | None:
    """This run's autosave, once its session has changed (claim_autosave set the last run's aside)."""
    path = autosave_path()
    return path if path.is_file() else None


def claim_autosave() -> Path | None:
    """Set the autosave the last run left behind out of this run's way, and return it (None: there is none).

    A core calls this once at launch, before its session can change. Every autosave replaces
    `autosave/session.badshop`, so without this the new session's first change would overwrite what a
    crashed run left there before anyone could restore it (spec §9: the next launch offers to restore it;
    §10: a restarted core reopens it). The file is moved to `autosave/previous.badshop` and that path is
    returned. With nothing to move (the last run changed nothing, or crashed again before it did), a
    previous.badshop that no later run replaced is still returned, so the offer outlives a crash loop.
    Creates nothing and never raises: a file that can't be moved stays where it is and None is returned
    (a folder that refuses the rename usually refuses the autosave's temp file too, so the file waits for the
    next launch)."""
    path = autosave_path()
    previous = path.with_name(f"previous{EXT}")
    try:
        with contextlib.suppress(FileNotFoundError):
            os.replace(path, previous)
        return previous if previous.is_file() else None
    except OSError:
        return None
