"""Compare Mac image pixels with the Linux fixtures across native codec builds."""
import sys

import pytest

from test_golden import CASES, _golden, run_case


@pytest.mark.skipif(sys.platform != "darwin", reason="native macOS image compatibility")
@pytest.mark.parametrize("case_id", [
    pytest.param(case, marks=[pytest.mark.models] if needs_model else [])
    for case, (tool, _, needs_model) in CASES.items() if tool != "text"
])
def test_macos_image_pixels(tmp_path, case_id):
    # PNG compression varies between Pillow's OS wheels. Compare every decoded
    # frame, dimensions, format and tool result. Linux CI also checks file bytes.
    # Caption layout depends on native font shaping; test_text compares those
    # pixels with the reference engine running on the same Mac.
    got = run_case(case_id, tmp_path)
    expected = _golden()["cases"][case_id]
    assert got["lines"] == expected["lines"]
    assert got["data"] == expected["data"]
    assert list(got["files"]) == list(expected["files"])
    for name, record in expected["files"].items():
        actual = {key: value for key, value in got["files"][name].items() if key != "sha256"}
        wanted = {key: value for key, value in record.items() if key != "sha256"}
        assert actual == wanted, name
