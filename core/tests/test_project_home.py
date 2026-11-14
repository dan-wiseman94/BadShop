import base64
import io

import pytest
from PIL import Image

from badshop.server.settings import load_settings
from test_server_app import Client, Failed, imported, run
from test_server_app import env as env


@pytest.mark.usefixtures("env")
def test_recent_projects_persist_preview_and_forgetting_never_deletes_file(env):
    async def body(app):
        client = Client(app)
        await client.call("session.new", name="My collage")
        image = await imported(client)
        step = await client.call("tools.run", tool="transform", params={"image": image, "width": 80, "height": 60})
        path = env / "collage.badshop"
        await client.call("session.save_as", path=str(path))
        rows = await client.call("projects.recent")
        assert len(rows) == 1
        assert rows[0]["name"] == "My collage"
        assert rows[0]["available"] is True
        preview = Image.open(io.BytesIO(base64.b64decode(rows[0]["thumbnail"])))
        assert preview.size == (80, 60)
        assert preview.tobytes() == app.session.artifacts.image(step["outputs"][0]).tobytes()
        assert load_settings().recent_projects[0].path == str(path)
        await client.call("session.open", path=str(path))
        assert len(await client.call("projects.recent")) == 1
        with pytest.raises(Failed):
            await Client(app, "cli:codex").call("projects.recent")
        await client.call("projects.forget", path=str(path))
        assert await client.call("projects.recent") == []
        assert load_settings().recent_projects == []
        assert path.is_file()
    run(body)


@pytest.mark.usefixtures("env")
def test_recent_projects_report_missing_files_and_respect_history_preference(env):
    async def body(app):
        client = Client(app)
        path = env / "missing.badshop"
        await client.call("session.save_as", path=str(path))
        path.rename(env / "moved.badshop")
        assert (await client.call("projects.recent"))[0]["available"] is False
        await client.call("settings.set", values={"remember_history": False})
        await client.call("session.save_as", path=str(env / "private.badshop"))
        assert len(await client.call("projects.recent")) == 1
    run(body)
