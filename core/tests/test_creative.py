import io
import json

import pytest
from PIL import Image

from badshop.agent.context import model_result
from badshop.evaluation import FIXED_CASES, comparison_report, scorecard_report
from badshop.evaluation_checks import score_project
from badshop.evaluation_demo import make_demo
from badshop.session.models import Step
from badshop.session.project import open_project, save
from badshop.session.session import Session


def test_discovery_thumbnails_stay_out_of_model_text_without_mutating_step():
    data = {"candidates": [{"id": "photo", "title": "a cat", "thumbnail_data_url": "data:image/png;base64,AAA"}]}
    step = Step(id="s1", index=1, tool="fetch", actor="user", status="done", params={}, data=data)
    text = model_result(step)
    assert "thumbnail_data_url" not in text
    assert "base64" not in text
    assert "a cat" in text
    assert step.data == data


def fixture_manifest(tmp_path, label="Before"):
    session = Session.new()
    with Image.new("RGB", (40, 20), "blue") as image, io.BytesIO() as out:
        image.save(out, "PNG")
        meta = session.artifacts.add(out.getvalue(), "result")
    save(session, tmp_path / "case.badshop")
    manifest = tmp_path / "runs.json"
    entries = [{"case_id": "dog-boss", "label": label, "project": "case.badshop", "artifact_id": meta.id[:8]}]
    manifest.write_text(json.dumps(entries))
    return manifest, meta


def test_report_embeds_exact_artifact_and_escapes_labels(tmp_path):
    manifest, meta = fixture_manifest(tmp_path, '<script>alert("x")</script>')
    report = comparison_report(manifest)
    assert "data:image/png;base64," in report
    assert meta.id in report
    assert "40 × 20" in report
    assert '<script>alert("x")</script>' not in report
    assert "&lt;script&gt;" in report
    assert "Download ratings" in report
    assert "Subject recognition" in report
    assert "https://" not in report  # portable and no third-party scripts or styles


def test_report_refuses_unknown_cases_and_duplicate_outputs(tmp_path):
    manifest, _ = fixture_manifest(tmp_path)
    entries = json.loads(manifest.read_text())
    manifest.write_text(json.dumps(entries * 2))
    with pytest.raises(ValueError, match="duplicate"):
        comparison_report(manifest)
    entries[0]["case_id"] = "invented"
    manifest.write_text(json.dumps(entries))
    with pytest.raises(ValueError, match="unknown case_id"):
        comparison_report(manifest)


def test_offline_demo_scores_six_real_before_after_projects(tmp_path):
    gallery = make_demo(tmp_path / "demo")
    manifest = gallery.parent / "runs.json"
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    scores = json.loads((gallery.parent / "scorecard.json").read_text(encoding="utf-8"))
    assert len(FIXED_CASES) == 6
    assert len(entries) == len(scores) == 16  # five pairs and two sets of three takes
    assert len({entry["project"] for entry in entries}) == 12
    assert all((gallery.parent / entry["project"]).is_file() for entry in entries)
    seed = open_project(gallery.parent / "inputs" / "preserve-concept-seed.badshop", output_dir=tmp_path)
    assert [step.params["text"] for step in seed.data.steps] == ["ANOTHER MEETING"]
    expected = {
        "dog-boss": "Duplicate take",
        "head-swap": "Input · distractor",
        "museum": "Brief restraint",
        "caption-overflow": "Caption placement · s1",
        "preserve-concept": "Original caption base",
        "fried-recognition": "Fry intensity",
    }
    for row in scores:
        failures = {check["name"] for check in row["checks"] if check["status"] == "fail"}
        if row["phase"] == "before":
            assert expected[row["case_id"]] in failures
        else:
            assert not failures, row
    assert scores[0]["counts"] == {"repeated_calls": 2, "repeated_outputs": 2, "placement_retries": 2}
    assert scores[3]["counts"] == {"repeated_calls": 0, "repeated_outputs": 0, "placement_retries": 0}
    report = gallery.read_text(encoding="utf-8")
    assert report.count("<h3>Before</h3>") == report.count("<h3>After</h3>") == 6
    assert report.count("<article ") == 16
    with pytest.raises(FileExistsError):
        make_demo(gallery.parent)
    assert gallery.read_text(encoding="utf-8") == report


def test_scorecard_uses_saved_export_record_without_opening_its_path(tmp_path):
    session = Session.new(output_dir=tmp_path)
    with Image.new("RGB", (40, 20), "blue") as image, io.BytesIO() as out:
        image.save(out, "PNG")
        source = session.import_image(out.getvalue(), "source.png").id
    edit = session.run_tool("filter", {"image": source, "names": ["invert"]}, "agent:fixture")
    output = edit.outputs[0]
    export = session.run_tool("export", {"image": output, "name": "proof"}, "agent:fixture")
    assert export.status == "done"
    (tmp_path / "proof.png").unlink()
    save(session, tmp_path / "export.badshop")
    manifest = tmp_path / "runs.json"
    entry = {"case_id": "dog-boss", "label": "Recorded", "project": "export.badshop",
             "artifact_id": output, "inputs": {"dog": source}, "expect_export": True}
    manifest.write_text(json.dumps([entry]), encoding="utf-8")
    checks = {check["name"]: check for check in json.loads(scorecard_report(manifest))[0]["checks"]}
    assert checks["Export record"]["status"] == "pass"
    assert "Current file presence is unverified" in checks["Export record"]["detail"]
    assert str(tmp_path) not in scorecard_report(manifest)
    entry["start_after"] = edit.id
    manifest.write_text(json.dumps([entry]), encoding="utf-8")
    checks = {check["name"]: check for check in json.loads(scorecard_report(manifest))[0]["checks"]}
    assert checks["Completed output"]["status"] == "fail"


def test_scorecard_flags_stacked_paste_as_review(tmp_path):
    session = Session.new(output_dir=tmp_path)
    for color in ("blue", "red"):
        with Image.new("RGB", (40, 40), color) as image, io.BytesIO() as out:
            image.save(out, "PNG")
            session.import_image(out.getvalue(), f"{color}.png")
    base, piece = session.artifacts.ids()
    first = session.run_tool("paste", {"base": base, "piece": piece, "at": [5, 5], "width": 12}, "agent:fixture")
    second = session.run_tool("paste", {"base": first.outputs[0], "piece": piece, "at": [20, 5], "width": 12},
                              "agent:fixture")
    checks, counts = score_project(session, {"id": "dog-boss"}, second.outputs[0], {})
    assert counts["placement_retries"] == 0  # different base hashes
    finding, = [check for check in checks if check.name == "Possible stacked correction"]
    assert finding.status == "review" and second.id in finding.detail
