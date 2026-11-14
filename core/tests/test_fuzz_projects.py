"""Generate ZIP limit boundaries and corrupt real BadShop projects."""

import io
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given, settings, strategies as st
from PIL import Image

from badshop.archives import check_directory
from badshop.engine.errors import EngineError
from badshop.session import project
from badshop.session.artifacts import ArtifactStore
from badshop.session.models import Part, SessionData
from badshop.session.session import Session


@settings(max_examples=80, derandomize=True)
@given(
    sizes=st.lists(st.integers(0, 24), max_size=5),
    comment=st.binary(max_size=24),
    delta=st.tuples(*(st.integers(-1, 1) for _ in range(3))),
)
def test_zip_preflight_enforces_all_three_limits(sizes, comment, delta):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.comment = comment
        for index, size in enumerate(sizes):
            archive.writestr(f"{index}.bin", b"x" * size)

    # These archives have no extras, entry comments, or ZIP64 records.
    directory_size = sum(46 + len(f"{index}.bin") for index in range(len(sizes)))
    limits = dict(
        archive_bytes=len(stream.getvalue()) + delta[0],
        directory_bytes=directory_size + delta[1],
        members=len(sizes) + delta[2],
    )
    if min(delta) < 0:
        with pytest.raises(ValueError):
            check_directory(stream, **limits)
    else:
        check_directory(stream, **limits)
        assert stream.tell() == 0
        with zipfile.ZipFile(stream) as archive:
            assert len(archive.infolist()) == len(sizes)


@pytest.fixture(scope="module")
def saved_project():
    # Freeze one real archive for shrinking: logical IDs and timestamps vary
    # between imports, changing ZIP size and therefore draw constraints.
    with TemporaryDirectory(prefix="badshop-fuzz-fixture-") as folder:
        session = Session(SessionData(id="fixture", name="Fuzz project", created_at=0), ArtifactStore())
        try:
            image = io.BytesIO()
            with Image.new("RGB", (2, 2), "red") as pixels:
                pixels.save(image, "PNG")
            artifact = session.import_image(image.getvalue(), "fixture")
            session.add_message("user", [Part(type="image", artifact_id=artifact.id)])
            saved = project.save(session, Path(folder) / "original.badshop").read_bytes()
            return saved, session.data.model_copy(deep=True), artifact.id, session.artifacts.data(artifact.id)
        finally:
            session.artifacts.close()


@settings(max_examples=100, derandomize=True)
@given(data=st.data(), replacement=st.binary(max_size=8))
def test_corrupted_project_fails_cleanly_or_preserves_the_saved_artifact(saved_project, data, replacement):
    with TemporaryDirectory(prefix="badshop-fuzz-") as folder:
        root = Path(folder)
        saved, expected_session, artifact_id, expected_image = saved_project
        original = root / "original.badshop"
        original.write_bytes(saved)
        start = data.draw(st.integers(0, len(saved) - 1), label="mutation offset")
        end = data.draw(st.integers(start, min(start + 8, len(saved))), label="mutation end")
        candidate = root / "candidate.badshop"
        candidate.write_bytes(saved[:start] + replacement + saved[end:])

        try:
            reopened = project.open_project(candidate)
        except EngineError as error:
            assert error.message and error.hint
        else:
            try:
                assert reopened.data == expected_session
                assert reopened.artifacts.data(artifact_id) == expected_image
            finally:
                reopened.artifacts.close()

        assert set(root.iterdir()) == {original, candidate}
        assert original.read_bytes() == saved
        intact = project.open_project(original)
        try:
            assert intact.artifacts.data(artifact_id) == expected_image
        finally:
            intact.artifacts.close()
