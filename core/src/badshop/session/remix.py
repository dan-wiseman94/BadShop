"""A deliberately small, inspectable project for sharing one result and its edits."""
import io
import secrets
from pathlib import Path

from PIL import Image

from badshop.engine.errors import EngineError
from badshop.session import project
from badshop.session.session import Session
from badshop.tools.registry import REGISTRY, image_refs, map_image_refs


def dependencies(session: Session, artifact_id: str) -> tuple[list[str], list[int]]:
    selected = session.artifacts.resolve(artifact_id)
    if selected not in session.visible_artifact_ids():
        raise EngineError("choose a picture in the current direction")
    artifacts: set[str] = set()
    steps: set[int] = set()
    pending = [(selected, len(session.data.steps))]
    visited: set[tuple[str, int]] = set()
    while pending:
        aid, before = pending.pop()
        if (aid, before) in visited:
            continue
        visited.add((aid, before))
        artifacts.add(aid)
        for i in range(before - 1, -1, -1):
            step = session.data.steps[i]
            if step.status != "done" or aid not in step.outputs:
                continue
            spec = REGISTRY[step.tool]
            # Network results become frozen inputs; replay never fetches a source.
            if not spec.mutates or spec.network or spec.writes_files:
                break
            if step.tool == "text" and step.params.get("font"):
                raise EngineError("this remix uses a custom font", hint="use the default font and replay before sharing an editable remix, or share the finished image")
            steps.add(i)
            artifacts.update(step.outputs)
            raw = {"image": step.params["image"]} if step.bypassed else step.params
            cls = REGISTRY["transform"].params if step.bypassed else spec.params
            def collect(ref):
                pending.append((session.artifacts.resolve(ref), i))
                return ref
            map_image_refs(cls, raw, collect)
            break
        if len(artifacts) > 120 or len(steps) > 60:
            raise EngineError("this remix is too large", hint="share a shorter direction (up to 60 edits and 120 images)")
    return [aid for aid in session.artifacts.ids() if aid in artifacts], sorted(steps)


def inspect(session: Session, artifact_id: str) -> dict:
    ids, steps = dependencies(session, artifact_id)
    return {"artifact_ids": ids, "step_count": len(steps),
            "sources": [session.artifacts.meta[aid].source.model_dump(mode="json")
                        for aid in ids if session.artifacts.meta[aid].source]}


def _clean_image(session: Session, aid: str) -> bytes:
    """Re-encode visible pixels without EXIF, comments or original container metadata."""
    meta = session.artifacts.meta[aid]
    if meta.frames > 120 or meta.width * meta.height * meta.frames > 120_000_000:
        raise EngineError("a remix image exceeds the 120-frame / 120-megapixel limit")
    frames, durations = [], []
    try:
        for index in range(meta.frames):
            with session.artifacts.image(aid, index) as image:
                durations.append(image.info.get("duration", 100))
                # A new image carries pixels only, even when convert() copies image.info.
                clean = Image.new("RGBA", image.size)
                clean.paste(image.convert("RGBA"))
                frames.append(clean)
        buf = io.BytesIO()
        if len(frames) == 1:
            frames[0].save(buf, "PNG")
        else:
            frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:],
                           duration=durations, loop=0, disposal=2, optimize=False)
        return buf.getvalue()
    finally:
        for frame in frames:
            frame.close()


def export(session: Session, artifact_id: str, include_credits: bool = False) -> Path:
    ids, indices = dependencies(session, artifact_id)
    clean = Session.new("Remix", decoder=session.artifacts.decoder)
    mapped = {}
    for index, aid in enumerate(ids):
        source = session.artifacts.meta[aid].source if include_credits else None
        mapped[aid] = clean.artifacts.add(_clean_image(session, aid), f"picture-{index + 1}", source=source, new_use=True).id
    for index in indices:
        old = session.data.steps[index]
        tool = "transform" if old.bypassed else old.tool
        raw = {"image": old.params["image"]} if old.bypassed else dict(old.params)
        # File-name hints are not part of the joke.
        if "name" in raw:
            raw["name"] = None
        params = map_image_refs(REGISTRY[tool].params, raw, lambda ref: mapped[session.artifacts.resolve(ref)])
        inputs = set(image_refs(REGISTRY[tool].params, params))
        step = clean.propose(tool, params, 'user')
        step.status = 'done'
        step.outputs = [mapped[aid] for aid in old.outputs]
        step.output_ports = {key: mapped[aid] for key, aid in old.output_ports.items()}
        for key, aid in step.output_ports.items():
            clean.artifacts.meta[aid] = clean.artifacts.meta[aid].model_copy(update={
                'produced_by': step.id, 'invocation_id': step.invocation_id, 'output_key': key, 'inputs': tuple(inputs)})
    session.output_dir.mkdir(parents=True, exist_ok=True)
    path = session.output_dir / f"remix-{secrets.token_hex(8)}.badshop"
    # Own a new destination before project.save's atomic replace; never replace a user's file.
    with path.open("xb"):
        pass
    try:
        return project.save(clean, path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
