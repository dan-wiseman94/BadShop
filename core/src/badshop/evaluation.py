"""Build a portable, offline comparison sheet from explicit saved-project outputs.

This never calls a model or changes pixels. Human ratings are deliberately separate from
the mechanical artifact metadata, and can be downloaded as JSON from the report.
"""

import argparse
import base64
import hashlib
import html
import json
from collections import Counter
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path

from badshop.engine.errors import EngineError
from badshop.evaluation_checks import Check, score_project
from badshop.session.models import ArtifactMeta
from badshop.session.project import open_project


CASES = json.loads(files("badshop").joinpath("evaluation_cases.json").read_text(encoding="utf-8"))
FIXED_CASES = [case for case in CASES if case.get("fixed")]


@dataclass
class Review:
    case_id: str
    label: str
    phase: str | None
    meta: ArtifactMeta
    steps: int
    checks: list[Check]
    counts: dict[str, int]
    data: bytes

    @property
    def key(self) -> str:
        phase = f"{self.phase}:" if self.phase else ""
        return f"{self.case_id}:{phase}{self.label}:{self.meta.id}"


def _reviews(manifest: Path, *, embed: bool) -> list[Review]:
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries or len(entries) > 100:
        raise ValueError("manifest must be a list of 1–100 outputs")
    cases = {case["id"]: case for case in CASES}
    reviews: list[Review] = []
    fingerprints = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"entry {index + 1} must be an object")
        case_id = entry.get("case_id")
        if not isinstance(case_id, str) or case_id not in cases:
            raise ValueError(f"entry {index + 1}: unknown case_id {case_id!r}")
        if not all(isinstance(entry.get(key), str) and entry[key].strip()
                   for key in ("project", "artifact_id", "label")):
            raise ValueError(f"entry {index + 1}: project, artifact_id and label are required strings")
        project_path = (manifest.parent / entry["project"]).resolve()
        session = open_project(project_path)
        meta = session.artifacts.meta[session.artifacts.resolve(entry["artifact_id"])]
        phase = entry.get("phase")
        if phase not in (None, "before", "after"):
            raise ValueError(f"entry {index + 1}: phase must be before or after")
        checks, counts = score_project(session, cases[case_id], meta.id, entry)
        review = Review(case_id, entry["label"], phase, meta, len(session.data.steps), checks, counts,
                        session.artifacts.data(meta.id) if embed else b"")
        if review.key in fingerprints:
            raise ValueError(f"entry {index + 1}: duplicate case, label and artifact")
        fingerprints.add(review.key)
        reviews.append(review)

    totals = Counter((r.case_id, r.phase) for r in reviews if r.phase)
    variants = Counter((r.case_id, r.phase, r.meta.id) for r in reviews if r.phase)
    for review in reviews:
        target = cases[review.case_id].get("takes")
        if target and review.phase:
            count = totals[review.case_id, review.phase]
            unique = sum(case_id == review.case_id and phase == review.phase for case_id, phase, _ in variants)
            review.checks.append(Check("Distinct saved takes", "pass" if unique >= target else "fail",
                                       f"{unique} unique artifact hashes among {count} selected takes; expected {target}."))
        if review.phase and variants[review.case_id, review.phase, review.meta.id] > 1:
            review.checks.append(Check("Duplicate take", "fail", "Another take in this phase has identical bytes."))
    return reviews


def scorecard_report(manifest: Path) -> str:
    return json.dumps([
        {"case_id": r.case_id, "label": r.label, "phase": r.phase, "artifact_id": r.meta.id,
         "timeline_steps": r.steps, "counts": r.counts, "checks": [asdict(check) for check in r.checks]}
        for r in _reviews(manifest, embed=False)
    ], indent=2) + "\n"


def comparison_report(manifest: Path) -> str:
    cases = {case["id"]: case for case in CASES}
    groups: dict[str, dict[str | None, list[str]]] = {}
    fingerprints = []
    e = html.escape
    for review in _reviews(manifest, embed=True):
        meta = review.meta
        data = base64.b64encode(review.data).decode("ascii")
        fingerprints.append(review.key)
        ratings = "".join(
            f'<label>{title}<select data-rating="{name}"><option value="">Unrated</option>'
            + "".join(f'<option value="{score}">{score}</option>' for score in range(1, 6))
            + "</select></label>"
            for name, title in (("recognition", "Subject recognition"), ("readability", "Joke readability"),
                                ("variety", "Distinctness of concept"), ("style", "Deliberately bad style"))
        )
        checks = "".join(f'<li><strong>{e(c.status.upper())} · {e(c.name)}</strong> {e(c.detail)}</li>'
                         for c in review.checks)
        counts = " · ".join(f"{name.replace('_', ' ')}: {count}" for name, count in review.counts.items())
        groups.setdefault(review.case_id, {}).setdefault(review.phase, []).append(
            f'<article data-key="{e(review.key)}"><h4>{e(review.label)}</h4>'
            f'<img src="data:{e(meta.mime)};base64,{data}" alt="{e(review.label)}">'
            f'<p>{meta.width} × {meta.height} · {e(meta.format)} · {review.steps} timeline steps</p>'
            f'<details open><summary>Saved-project checks</summary><ul>{checks}</ul><p>{counts}</p></details>'
            f'<p class="hash">Artifact {meta.id}</p>{ratings}'
            '<label>Concrete failures or strengths<textarea data-rating="notes"></textarea></label>'
            '<label><input type="checkbox" data-rating="favorite"> Preferred result</label></article>'
        )
    sections = []
    for case_id, phases in groups.items():
        columns = "".join(
            f'<div class="phase"><h3>{phase.title() if phase else "Selected outputs"}</h3>'
            f'<div class="variants">{"".join(phases[phase])}</div></div>'
            for phase in ("before", "after", None) if phase in phases
        )
        sections.append(
            f'<section><h2>{e(case_id)}</h2><p>{e(cases[case_id]["prompt"])}</p>'
            f'<p>Look for {e(", ".join(cases[case_id]["focus"]))}.</p><div class="phases">{columns}</div></section>'
        )
    report_id = hashlib.sha256("\n".join(fingerprints).encode()).hexdigest()
    return """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>badshop comparison</title><style>
body{font:16px system-ui;margin:24px;background:#151515;color:#eee}h1,h2,h3{line-height:1.2}
.phases{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:20px}
.phase{min-width:0}details{margin-bottom:16px}li{margin:6px 0}
.variants{display:flex;gap:20px;overflow-x:auto;align-items:flex-start}article{flex:1 0 280px;max-width:600px;
padding:16px;background:#242424;border:1px solid #555}img{width:100%;height:320px;object-fit:contain}
label{display:block;margin:12px 0}select{margin-left:12px}textarea{display:block;box-sizing:border-box;
width:100%;min-height:70px}section{margin:32px 0}.hash{font:11px monospace;overflow-wrap:anywhere}
button{padding:10px 16px}#status{margin-left:12px}
</style><h1>badshop comparison</h1>
<p>Human review: 1 = fails, 3 = usable, 5 = strong. Distinctness is relative to the other takes.
Rough edges are intentional. Rate recognizability and readability without rewarding polish.</p>
<p>Use the same input files and provider settings across runs. Checks summarize recorded evidence.
Review the images and download your ratings to keep a copy.</p>
<button id="download" type="button">Download ratings</button><span id="status" role="status"></span>
""" + "".join(sections) + """<script>
const reportId = '""" + report_id + """';
const storageKey = 'badshop-evaluation:' + reportId;
let saved = {};
try { saved = JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch {}
for (const card of document.querySelectorAll('article')) {
  for (const field of card.querySelectorAll('[data-rating]')) {
    const value = saved[card.dataset.key]?.[field.dataset.rating];
    if (field.type === 'checkbox') field.checked = value === true;
    else if (value !== undefined) field.value = value;
    field.addEventListener('input', () => {
      saved[card.dataset.key] ??= {};
      saved[card.dataset.key][field.dataset.rating] = field.type === 'checkbox' ? field.checked : field.value;
      try { localStorage.setItem(storageKey, JSON.stringify(saved)); }
      catch { document.querySelector('#status').textContent = 'Browser storage unavailable; download to keep ratings.'; }
    });
  }
}
document.querySelector('#download').addEventListener('click', () => {
  const blob = new Blob([JSON.stringify({report_id: reportId, ratings: saved}, null, 2)], {type:'application/json'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = 'badshop-ratings.json';
  document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
</script></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?", help="JSON list of saved outputs")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--cases", action="store_true", help="print the six fixed briefs")
    modes.add_argument("--scorecard", action="store_true", help="write deterministic checks as JSON")
    modes.add_argument("--demo", type=Path, help="create a new directory with a complete offline example")
    parser.add_argument("--out", type=Path, help="output path")
    parser.add_argument("--force", action="store_true", help="replace an existing report")
    args = parser.parse_args()
    if args.cases:
        print(json.dumps(FIXED_CASES, indent=2))
        return
    try:
        if args.demo:
            if args.manifest or args.out or args.force:
                parser.error("--demo takes a new directory and no other output arguments")
            from badshop.evaluation_demo import make_demo

            print(make_demo(args.demo))
            return
        if args.manifest is None:
            parser.error("give a manifest, --cases or --demo")
        path = args.out or Path("badshop-scorecard.json" if args.scorecard else "badshop-comparison.html")
        report = scorecard_report(args.manifest) if args.scorecard else comparison_report(args.manifest)
        with path.open("w" if args.force else "x", encoding="utf-8") as output:
            output.write(report)
    except (OSError, ValueError, KeyError, EngineError) as error:
        parser.error(str(error))
    print(path.resolve())


if __name__ == "__main__":
    main()
