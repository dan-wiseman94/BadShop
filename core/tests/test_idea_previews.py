import io

import pytest
from PIL import Image

from badshop.engine.errors import EngineError
from badshop.session.session import Session


def test_personal_preview_matches_committed_pixels_without_changing_project():
    session = Session.new()
    out = io.BytesIO()
    Image.new("RGB", (90, 70), "#e13172").save(out, "PNG")
    source = session.artifacts.add(out.getvalue(), "my character")
    params = {"template": "trading-card", "images": [source.id], "title": "My character", "captions": ["Zero skills"]}
    before = session.data.model_dump_json()
    preview = session.preview_tool("layout", params)
    assert session.data.model_dump_json() == before
    committed = session.run_tool("layout", params, "user")
    assert committed.status == "done"
    assert preview[0].data == session.artifacts.data(committed.outputs[0])


@pytest.mark.parametrize("tool,params", [("fetch", {"query": "dog"}), ("export", {"image": "missing"})])
def test_preview_refuses_network_and_file_writes(tool, params):
    session = Session.new()
    with pytest.raises(EngineError, match="local image tool"):
        session.preview_tool(tool, params)
    assert not session.data.steps
