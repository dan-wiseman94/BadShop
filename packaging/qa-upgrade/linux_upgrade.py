import csv
import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import psutil
from PIL import Image
from native_windows import visible_window, screenshot
from smoke_desktop import is_core
from staged_feed import StagedFeed


def wait(predicate, what, timeout=45):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if value := predicate():
            return value
        time.sleep(.25)
    raise AssertionError(what)


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def keys(*names):
    command("xdotool", "key", "--clearmodifiers", *names)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Desktop:
    def __init__(self, evidence):
        self.evidence = evidence
        self.window = None
        self.crop = None

    def lines(self):
        screen = self.evidence / "current.png"
        screenshot(self.window, screen)
        with Image.open(screen) as frame:
            bounds = self.crop or (0, 0, frame.width, frame.height)
            trimmed = frame.crop(bounds)
            trimmed.resize((trimmed.width * 2, trimmed.height * 2)).save(self.evidence / "ocr.png")
        tsv = command("tesseract", str(self.evidence / "ocr.png"), "stdout", "--psm", "11", "tsv")
        groups = {}
        for row in csv.DictReader(tsv.splitlines(), delimiter="\t"):
            if (row.get("text") or "").strip():
                key = tuple(row[k] for k in ("block_num", "par_num", "line_num"))
                groups.setdefault(key, []).append(row)
        return groups.values()

    def find(self, phrase, *, click=False, timeout=45, exact=False):
        def locate():
            for words in self.lines():
                text = " ".join(w["text"] for w in words)
                if (phrase.casefold() == text.casefold() if exact else phrase.casefold() in text.casefold()):
                    if click:
                        word = next((w for w in words if phrase.casefold().startswith(w["text"].casefold())), words[0])
                        command("xdotool", "mousemove", "--window", str(self.window),
                                str((self.crop[0] if self.crop else 0) + int(word["left"]) // 2 + int(word["width"]) // 4),
                                str((self.crop[1] if self.crop else 0) + int(word["top"]) // 2 + int(word["height"]) // 4), "click", "1")
                    return text
        value = wait(locate, f"Missing visible text {phrase!r}", timeout)
        print(f"UI: {value}", flush=True)
        return value


def main(root, evidence, downloads):
    root.mkdir(exist_ok=True)
    for args in (
        ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem",
         "-days", "2", "-subj", "/CN=BadShop local draft QA CA", "-addext", "basicConstraints=critical,CA:TRUE"],
        ["req", "-newkey", "rsa:2048", "-nodes", "-keyout", "server.key", "-out", "server.csr", "-subj", "/CN=github.com"],
        ["x509", "-req", "-in", "server.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial",
         "-out", "server.pem", "-days", "2", "-extfile", "server.ext"],
    ):
        (root / "server.ext").write_text("subjectAltName=DNS:github.com\nextendedKeyUsage=serverAuth\n")
        subprocess.run(["openssl", *args], cwd=root, check=True, capture_output=True)

    feed = StagedFeed(root, downloads)
    appimage = root / "badshop.AppImage"
    shutil.copy2(root.parent / appimage.name, appimage)
    print("AppImage before:", digest(appimage), flush=True)
    assert digest(appimage) == "b7446fdcab8c4f9b7744dff5574ac7cbfa65822caf5e4d70988a767f08933e4b"
    ready = root / "ready.json"
    nonce = secrets.token_hex(12)
    env = {**os.environ,
           **{key: str(root / key.lower()) for key in (
               "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME",
               "BADSHOP_CONFIG_DIR", "BADSHOP_DATA_DIR", "BADSHOP_LOG_DIR", "BADSHOP_OUT")},
           "HTTPS_PROXY": feed.url, "https_proxy": feed.url, "SSL_CERT_FILE": str(root / "ca.pem"),
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
           "BADSHOP_SMOKE_READY_FILE": str(ready), "BADSHOP_SMOKE_NONCE": nonce,
           "GDK_BACKEND": "x11", "WEBKIT_DISABLE_COMPOSITING_MODE": "1"}
    for name in ("WAYLAND_DISPLAY", "APPIMAGE_EXTRACT_AND_RUN", "ALL_PROXY", "all_proxy", "SSL_CERT_DIR"):
        env.pop(name, None)
    ui = Desktop(evidence)
    with (evidence / "app.log").open("w") as log:
        p = subprocess.Popen([str(appimage)], env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            def state():
                try:
                    current = json.loads(ready.read_text())
                    if current["nonce"] == nonce:
                        return current
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
            current = wait(state, "No installed renderer readiness")
            ui.window = wait(lambda: visible_window(current["shell_pid"]), "No visible native window")
            command("xdotool", "windowfocus", str(ui.window))
            if current["welcome"]:
                keys("Return")
                wait(lambda: (s := state()) and not s["welcome"], "Welcome did not close")
            project = root / "upgrade-fixture.badshop"
            def paste(color):
                png = root / "clipboard.png"
                Image.new("RGBA", (40, 30), color).save(png)
                clipboard = subprocess.Popen(["xclip", "-selection", "clipboard", "-t", "image/png", "-i", str(png), "-quiet"],
                                             stdout=log, stderr=log)
                try:
                    time.sleep(.25)
                    keys("ctrl+v")
                    wait(lambda: (s := state()) and s["unsaved"], "Image paste did not dirty session")
                finally:
                    clipboard.terminate()
                    clipboard.wait(timeout=5)

            def click(x, y):
                command("xdotool", "mousemove", "--window", str(ui.window), str(x), str(y), "click", "1")

            def update_panel():
                ui.crop = None
                click(width - 144, 34)
                ui.find("Updates", click=True)
                ui.crop = (477, 303, 1110, 744)

            paste((12, 90, 150, 255))
            keys("ctrl+s")
            def file_dialog(kind, path):
                def locate():
                    result = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", kind],
                                            capture_output=True, text=True)
                    return next(iter(result.stdout.splitlines()), None)
                dialog = wait(locate, f"Native {kind} dialog did not open", timeout=12)
                command("xdotool", "windowfocus", dialog)
                if kind == "^Save":
                    command("xdotool", "mousemove", "--window", dialog, "140", "27", "click", "1")
                    keys("ctrl+a")
                else:
                    keys("ctrl+l")
                command("xdotool", "type", "--clearmodifiers", str(path))
                keys("Return")
                time.sleep(.5)
                command("xdotool", "windowfocus", str(ui.window))

            file_dialog("^Save", project)
            wait(project.is_file, "Native Save As did not write the project")
            wait(lambda: (s := state()) and not s["unsaved"], "Saved project stayed dirty")
            before = digest(project)
            print("Saved project before upgrade:", before, flush=True)
            shutil.copyfile(project, evidence / "pre-update-project.badshop")

            paste((225, 70, 10, 255))
            screenshot(ui.window, evidence / "initial.png")
            width = Image.open(evidence / "initial.png").width
            update_panel()
            ui.find("Check for updates", click=True, exact=True)
            ui.find("0.4.2 is available", timeout=40)
            screenshot(ui.window, evidence / "candidate-found.png")
            old_pid = state()["shell_pid"]
            children = psutil.Process(old_pid).children(recursive=True)
            assert any(is_core(child) for child in children), "Old shell has no owned core"

            for mode, expected in (("interrupt", "error decoding response body"), ("tampered", "signature")):
                feed.mode = mode
                ui.find("install update", click=True)
                ui.find("You can retry", timeout=65)
                ui.find(expected, timeout=5)
                screenshot(ui.window, evidence / f"{mode}-rejected.png")
                assert state()["shell_pid"] == old_pid and digest(project) == before
                assert digest(appimage) == "b7446fdcab8c4f9b7744dff5574ac7cbfa65822caf5e4d70988a767f08933e4b"

            feed.mode = "valid"
            ui.find("install update", click=True)
            ui.crop = (451, 388, 990, 554)
            ui.find("Save changes", timeout=150)
            screenshot(ui.window, evidence / "save-before-restart.png")
            click(912, 508)
            updated = wait(lambda: (s := state()) and s["shell_pid"] != old_pid and s, "Update did not restart into a ready app", timeout=90)
            assert digest(appimage) == digest(feed.asset), "Updated AppImage differs from signed release bytes"
            after = digest(project)
            assert before != after, "Update did not save pending changes"
            with zipfile.ZipFile(project) as bundle:
                artifacts = {Path(name).stem: hashlib.sha256(bundle.read(name)).hexdigest()
                             for name in bundle.namelist() if name.startswith("artifacts/")}
            with zipfile.ZipFile(evidence / "pre-update-project.badshop") as saved:
                original_artifacts = {Path(name).stem: hashlib.sha256(saved.read(name)).hexdigest()
                                      for name in saved.namelist() if name.startswith("artifacts/")}
            assert len(artifacts) == 4 and original_artifacts.items() <= artifacts.items(), artifacts
            assert all(key == value for key, value in artifacts.items()), artifacts
            wait(lambda: not any(p.is_running() and p.status() != psutil.STATUS_ZOMBIE for p in children if is_core(p)),
                 "A pre-update core or worker survived")
            ui.window = wait(lambda: visible_window(updated["shell_pid"]), "Updated window not visible")
            command("xdotool", "windowfocus", str(ui.window))
            update_panel()
            ui.find("Check for updates", click=True, exact=True)
            ui.find("Installed version: 0.4.2")
            screenshot(ui.window, evidence / "updated-version.png")
            click(1090, 222)
            keys("ctrl+o")
            file_dialog("^Open", project)
            ui.crop = None
            ui.find("4 images")
            screenshot(ui.window, evidence / "reopened.png")
            assert digest(project) == after
            shutil.copyfile(project, evidence / "post-update-project.badshop")
            (evidence / "summary.json").write_text(json.dumps(
                {"platform": "linux-x64 AppImage on Arch WSL", "result": "passed",
                 "appimage_sha256": digest(appimage), "project_before": before,
                 "project_after": after, "artifact_sha256": artifacts,
                 "old_core_cleanup": True, "requests": feed.requests}, indent=2))
        finally:
            feed.server.shutdown()
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            p.wait(timeout=15)


if __name__ == "__main__":
    main(*(Path(x).resolve() for x in sys.argv[1:]))
