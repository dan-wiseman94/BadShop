import io
import json

import pytest
from PIL import Image

from badshop.agent.context import model_result
from badshop.evaluation import comparison_report
from badshop.session.models import Step
from badshop.session.project import save
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
