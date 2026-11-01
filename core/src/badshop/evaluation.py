"""Build a portable, offline comparison sheet from explicit saved-project outputs.

This never calls a model or changes pixels. Human ratings are deliberately separate from
the mechanical artifact metadata, and can be downloaded as JSON from the report.
"""

import argparse
import base64
import hashlib
import html
import json
from importlib.resources import files
from pathlib import Path

from badshop.engine.errors import EngineError
from badshop.session.project import open_project


CASES = json.loads(files("badshop").joinpath("evaluation_cases.json").read_text(encoding="utf-8"))


def comparison_report(manifest: Path) -> str:
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries or len(entries) > 100:
        raise ValueError("manifest must be a list of 1–100 outputs")
    cases = {case["id"]: case for case in CASES}
    groups: dict[str, list[str]] = {}
    fingerprints = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"entry {index + 1} must be an object")
        case_id = entry.get("case_id")
        if case_id not in cases:
            raise ValueError(f"entry {index + 1}: unknown case_id {case_id!r}")
        if not all(isinstance(entry.get(key), str) and entry[key].strip()
                   for key in ("project", "artifact_id", "label")):
            raise ValueError(f"entry {index + 1}: project, artifact_id and label are required strings")
        project_path = (manifest.parent / entry["project"]).resolve()
        session = open_project(project_path)
        meta = session.artifacts.meta[session.artifacts.resolve(entry["artifact_id"])]
        data = base64.b64encode(session.artifacts.data(meta.id)).decode("ascii")
        e = html.escape
        key = f"{case_id}:{entry['label']}:{meta.id}"
        if key in fingerprints:
            raise ValueError(f"entry {index + 1}: duplicate case, label and artifact")
        fingerprints.append(key)
        ratings = "".join(
            f'<label>{title}<select data-rating="{name}"><option value="">Unrated</option>'
            + "".join(f'<option value="{score}">{score}</option>' for score in range(1, 6))
            + "</select></label>"
            for name, title in (("recognition", "Subject recognition"), ("readability", "Joke readability"),
                                ("variety", "Distinctness of concept"), ("style", "Deliberately bad style"))
        )
        groups.setdefault(case_id, []).append(
            f'<article data-key="{e(key, quote=True)}"><h3>{e(entry["label"])}</h3>'
            f'<img src="data:{meta.mime};base64,{data}" alt="{e(entry["label"], quote=True)}">'
            f'<p>{meta.width} × {meta.height} · {e(meta.format)} · {len(session.data.steps)} steps</p>'
            f'<p class="hash">Artifact {meta.id}</p>{ratings}'
            '<label>Concrete failures or strengths<textarea data-rating="notes"></textarea></label>'
            '<label><input type="checkbox" data-rating="favorite"> Preferred result</label></article>'
        )
    sections = "".join(
        f'<section><h2>{html.escape(case_id)}</h2><p>{html.escape(cases[case_id]["prompt"])}</p>'
        f'<p>Look for: {html.escape(", ".join(cases[case_id]["focus"]))}</p>'
        f'<div class="variants">{"".join(cards)}</div></section>'
        for case_id, cards in groups.items()
    )
    report_id = hashlib.sha256("\n".join(fingerprints).encode()).hexdigest()
    return """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>badshop comparison</title><style>
body{font:16px system-ui;margin:24px;background:#151515;color:#eee}h1,h2,h3{line-height:1.2}
.variants{display:flex;gap:20px;overflow-x:auto;align-items:flex-start}article{flex:1 0 280px;max-width:600px;
padding:16px;background:#242424;border:1px solid #555}img{width:100%;height:320px;object-fit:contain}
label{display:block;margin:12px 0}select{margin-left:12px}textarea{display:block;box-sizing:border-box;
width:100%;min-height:70px}section{margin:32px 0}.hash{font:11px monospace;overflow-wrap:anywhere}
button{padding:10px 16px}#status{margin-left:12px}
</style><h1>badshop comparison</h1>
<p>Human review: 1 = fails, 3 = usable, 5 = strong. Distinctness is relative to the other takes.
Rough edges are intentional. Rate recognizability and readability without rewarding polish.</p>
<p>Use the same input files and provider settings across runs. These are selected saved outputs,
not an automated humor benchmark. Ratings remain in this browser; download them to keep a copy.</p>
<button id="download" type="button">Download ratings</button><span id="status" role="status"></span>
""" + sections + """<script>
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
    parser.add_argument("--cases", action="store_true", help="print the fixed prompt set")
    parser.add_argument("--out", type=Path, default=Path("badshop-comparison.html"))
    parser.add_argument("--force", action="store_true", help="replace an existing report")
    args = parser.parse_args()
    if args.cases:
        print(json.dumps(CASES, indent=2))
        return
    if args.manifest is None:
        parser.error("give a manifest or --cases")
    try:
        report = comparison_report(args.manifest)
        with args.out.open("w" if args.force else "x", encoding="utf-8") as output:
            output.write(report)
    except (OSError, ValueError, KeyError, EngineError) as error:
        parser.error(str(error))
    print(args.out.resolve())


if __name__ == "__main__":
    main()
