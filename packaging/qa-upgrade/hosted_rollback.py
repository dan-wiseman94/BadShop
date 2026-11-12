import contextlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import psutil

from hosted_upgrade import Mac, Windows, WINDOWS, artifacts, install
from linux_upgrade import digest, wait


def main(old, backup, upgraded, root, evidence):
    root.mkdir()
    evidence.mkdir(exist_ok=True)
    exe = install(old, root / "installed")
    project = root / "rollback-backup.badshop"
    shutil.copyfile(backup, project)
    future = root / "newer-schema.badshop"
    with zipfile.ZipFile(upgraded) as valid, zipfile.ZipFile(future, "w") as invalid:
        for name in valid.namelist():
            content = valid.read(name)
            if name == "session.json":
                value = json.loads(content)
                value["schema"] = 999
                content = json.dumps(value).encode()
            invalid.writestr(name, content)

    ready = root / "ready.json"
    nonce = secrets.token_hex(12)
    env = {**os.environ, **{key: str(root / key.lower()) for key in (
        "BADSHOP_CONFIG_DIR", "BADSHOP_DATA_DIR", "BADSHOP_LOG_DIR", "BADSHOP_OUT")},
        "HTTPS_PROXY": "http://127.0.0.1:1", "https_proxy": "http://127.0.0.1:1",
        "NO_PROXY": "127.0.0.1,localhost,tauri.localhost",
        "BADSHOP_SMOKE_READY_FILE": str(ready), "BADSHOP_SMOKE_NONCE": nonce,
        "WEBVIEW2_USER_DATA_FOLDER": str(root / "webview"),
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": "--remote-debugging-port=0"}
    env.pop("BADSHOP_FAKE_PROVIDER", None)

    def state():
        try:
            value = json.loads(ready.read_text())
            if value["nonce"] == nonce:
                return value
        except (OSError, ValueError):
            pass

    with contextlib.ExitStack() as stack:
        if WINDOWS:
            from playwright.sync_api import sync_playwright
            from smoke_windows_edit import runner_webview_policy
            stack.enter_context(runner_webview_policy(exe, root / "webview"))
            ui = Windows(stack.enter_context(sync_playwright()), root, evidence)
        else:
            ui = Mac(evidence)

        before = digest(project)
        schema_hash = digest(future)
        count = len(artifacts(project))
        log = stack.enter_context((evidence / "app.log").open("w"))
        proc = subprocess.Popen([str(exe)], env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            start = wait(state, "Rollback shell did not connect", timeout=90)
            ui.attach(start["shell_pid"])
            if start["welcome"]:
                ui.welcome()
                wait(lambda: (s := state()) and not s["welcome"], "Rollback welcome did not dismiss")

            def open_project(path):
                if WINDOWS:
                    ui.page.locator(".session-name").click()
                    ui.page.get_by_role("button", name=re.compile(r"^Open session")).click()
                    ui.input_file(path)
                else:
                    import Quartz as q
                    ui.key(31, q.kCGEventFlagMaskCommand)
                    ui.open_path(path)
                    ui.press("Open")

            open_project(project)
            if WINDOWS:
                ui.page.get_by_text(re.compile(rf"\b{count} images\b")).wait_for()
                from smoke_windows_edit import viewer_hash
                assert viewer_hash(ui.page) in artifacts(project)
            else:
                ui.text(f"{count} images", footer=True)
            ui.shot("rollback-recovered")
            open_project(future)
            if WINDOWS:
                ui.page.get_by_text(re.compile("newer badshop")).wait_for()
            else:
                ui.text("newer badshop")
            ui.shot("future-schema-rejected")
            assert digest(project) == before and digest(future) == schema_hash
            (evidence / "summary.json").write_text(json.dumps({
                "status": "passed", "old_installer_sha256": digest(old),
                "reopened_backup_sha256": before, "future_schema_rejected_without_mutation": schema_hash,
            }, indent=2))
        finally:
            if hasattr(ui, "window"):
                with contextlib.suppress(Exception):
                    ui.shot("last")
            with contextlib.suppress(psutil.NoSuchProcess):
                shell = psutil.Process(proc.pid)
                children = shell.children(recursive=True)
                shell.terminate()
                _, running = psutil.wait_procs([shell, *children], timeout=12)
                for child in running:
                    with contextlib.suppress(psutil.NoSuchProcess):
                        child.kill()


if __name__ == "__main__":
    main(*(Path(x).resolve() for x in sys.argv[1:]))
