"""Build small, synthetic offline review projects using BadShop's ordinary tools."""

import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

from badshop.evaluation import FIXED_CASES, comparison_report, scorecard_report
from badshop.session.models import Part
from badshop.session.project import save
from badshop.session.session import Session

# An explicit, missing font name selects the engine's offline built-in fallback.
OFFLINE_FONT = "badshop-evaluation-fallback.ttf"
LABELS = {
    "dog": "Dog", "donor": "Donor", "target": "Target", "distractor": "Distractor",
    "painting": "Painting", "duck": "Duck", "canvas": "Canvas", "composite": "Captioned composite",
    "desk": "Office desk", "court": "Courtroom", "stage": "Board meeting",
}


def _fixture(name: str, path: Path) -> None:
    """Small original drawings. Their simple shapes make placement failures easy to spot."""
    portraits = {"donor": "#e4a479", "target": "#a0634d", "distractor": "#f0bd92", "composite": "#e4a479"}
    backgrounds = {"desk": "#4f7161", "court": "#76524e", "stage": "#364b7b"}
    is_piece = name in {"dog", "donor", "distractor", "duck"}
    size = (124, 114) if is_piece else ((320, 160) if name == "canvas" else (360, 250))
    image = Image.new("RGBA", size, (0, 0, 0, 0) if is_piece else backgrounds.get(name, "#b9b69a"))
    draw = ImageDraw.Draw(image)
    if name == "dog":
        draw.polygon([(20, 18), (49, 24), (20, 78)], fill="#593323")
        draw.polygon([(103, 18), (75, 24), (108, 78)], fill="#593323")
        draw.ellipse((31, 25, 95, 99), fill="#ce9356")
        draw.ellipse((49, 63, 77, 91), fill="#ead0a5")
        for x, y, width in ((44, 48, 7), (73, 48, 7), (59, 69, 10)):
            draw.ellipse((x, y, x + width, y + 7), fill="#241810")
    elif name == "duck":
        draw.ellipse((19, 49, 103, 101), fill="#ffce28")
        draw.ellipse((56, 14, 105, 64), fill="#ffce28")
        draw.polygon([(97, 39), (124, 51), (98, 56)], fill="#ef6d1b")
        draw.ellipse((83, 29, 89, 35), fill="black")
    elif name in portraits:
        x, y = (23, 12) if is_piece else (144, 39)
        if not is_piece:
            draw.polygon([(x - 32, 208), (x - 10, 123), (x + 82, 123), (x + 107, 208)], fill="#352d45")
        draw.ellipse((x, y, x + 74, y + 87), fill=portraits[name])
        draw.polygon([(x, y + 26), (x + 12, y), (x + 62, y), (x + 74, y + 19)], fill="#392a28")
        draw.rectangle((x + 16, y + 40, x + 23, y + 46), fill="#282222")
        draw.rectangle((x + 48, y + 40, x + 55, y + 46), fill="#282222")
        draw.line((x + 27, y + 66, x + 50, y + 67), fill="#79342e", width=3)
        if name == "composite":
            draw.rectangle((35, 209, 325, 244), fill="#27242c")
            draw.text((180, 226), "EXECUTIVE DECISION", anchor="mm", font_size=21, fill="white")
    elif name == "painting":
        draw.rectangle((12, 12, 348, 237), outline="#745827", width=14)
        draw.rectangle((27, 159, 333, 222), fill="#614436")
        draw.polygon([(154, 85), (204, 85), (194, 171), (164, 171)], fill="#ad3a32")
    elif name == "canvas":
        draw.rectangle((0, 85, 320, 160), fill="#738785")
        draw.ellipse((234, 14, 288, 68), fill="#e5d9a6")
        draw.polygon([(0, 114), (74, 60), (162, 112), (240, 73), (320, 129)], fill="#425c60")
    else:
        draw.rectangle((0, 159, 360, 250), fill="#4a3429")
        draw.rectangle((98, 168, 262, 232), fill="#decba7")
        draw.text((180, 200), LABELS[name].upper(), anchor="mm", font_size=22, fill="#382922")
    image.save(path)


def _project(case: dict, phase: str, directory: Path) -> list[dict]:
    case_id = case["id"]
    after = phase == "after"
    roles = case["roles"]
    names = list(roles)
    if case_id == "dog-boss":
        names.extend(("desk", "court", "stage"))
    session = Session.new(f"{case_id} · {phase}", output_dir=directory)
    images = {name: session.import_image((directory / "inputs" / f"{name}.png").read_bytes(), f"{name}.png").id
              for name in names}

    def run(tool: str, *, actor="agent:fixture", **params):
        step = session.run_tool(tool, params, actor)
        if step.status != "done":
            raise ValueError(f"demo {case_id}/{phase} {tool}: {step.result_text}")
        return step

    def caption(image, text, **options):
        return run("text", actor="user", image=image, text=text, font=OFFLINE_FONT, **options)

    extra = {}
    if case_id == "preserve-concept":
        previous = caption(images["canvas"], "ANOTHER MEETING", size=22)
        extra["start_after"] = previous.id
        if not after:
            save(session, directory / "inputs" / "preserve-concept-seed.badshop")
    session.add_message("user", [Part(type="text", text=case["prompt"]),
                                 *(Part(type="image", artifact_id=images[name]) for name in roles)])

    if case_id == "dog-boss":
        backgrounds = ("desk", "court", "stage") if after else ("desk",) * 3
        outputs = [run("paste", base=images[base], piece=images["dog"],
                       width=(118 + 12 * i) if after else 118,
                       at=[(40 + 65 * i) if after else 40, 55]).outputs[0] for i, base in enumerate(backgrounds)]
    elif case_id == "head-swap":
        outputs = run("paste", base=images["target"], piece=images["donor" if after else "distractor"],
                      width=110, at=[128, 24] if after else [-150, 24]).outputs
    elif case_id == "museum":
        paste = run("paste", base=images["painting"], piece=images["duck"], width=110, at=[124, 76])
        outputs = paste.outputs if after else caption(paste.outputs[0], "MUSEUM PRANK", size=25).outputs
    elif case_id == "caption-overflow":
        outputs = caption(images["canvas"], case["caption"], size=14 if after else 23,
                          at=[160, 52] if after else [160, 138], margin=12).outputs
    elif case_id == "preserve-concept":
        base = images["canvas"] if after else previous.outputs[0]
        outputs = caption(base, case["caption"], size=22, bottom=not after).outputs
    else:
        outputs = run("deepfry", image=images["composite"], level=2 if after else 5, seed=7).outputs

    path = save(session, directory / f"{case_id}-{phase}.badshop")
    return [{"case_id": case_id, "phase": phase, "label": f"{phase.title()} · take {index}",
             "project": path.name, "artifact_id": artifact, "inputs": {role: images[role] for role in roles}, **extra}
            for index, artifact in enumerate(outputs, 1)]


def make_demo(directory: Path) -> Path:
    directory = directory.resolve()
    directory.mkdir()
    try:
        (directory / "inputs").mkdir()
        for name in LABELS:
            _fixture(name, directory / "inputs" / f"{name}.png")
        entries = [entry for case in FIXED_CASES for phase in ("before", "after")
                   for entry in _project(case, phase, directory)]
        manifest = directory / "runs.json"
        manifest.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
        (directory / "scorecard.json").write_text(scorecard_report(manifest), encoding="utf-8")
        gallery = directory / "comparison.html"
        gallery.write_text(comparison_report(manifest), encoding="utf-8")
        return gallery
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
