import contextlib
import hashlib
import io
import json
import os
import plistlib
import platform
import re
import secrets
import shutil
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

from linux_upgrade import digest, wait

WINDOWS = sys.platform == "win32"


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, timeout=180, **kwargs)


def install(old, root):
    root.mkdir()
    if WINDOWS:
        run(old, "/S", f"/D={root}")
        return root / "badshop-desktop.exe"
    mount = root / "volume"
    mount.mkdir()
    run("hdiutil", "attach", old, "-readonly", "-nobrowse", "-noverify", "-mountpoint", mount, input=b"Y\n")
    try:
        app, = mount.glob("*.app")
        dest = root / app.name
        shutil.copytree(app, dest, symlinks=True)
    finally:
        run("hdiutil", "detach", mount)
    info = plistlib.loads((dest / "Contents/Info.plist").read_bytes())
    return (dest / "Contents/MacOS" / info["CFBundleExecutable"]).resolve()


def certificate(root):
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    def name(value):
        return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, value)])

    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = name("BadShop disposable upgrade QA root")
    leaf_name = name("github.com")

    def certificate(subject, issuer, public):
        return (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(public)
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(hours=1))
                .not_valid_after(now + timedelta(days=1))
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(public), critical=False))

    ca = (certificate(ca_name, ca_name, ca_key.public_key())
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, None, None), critical=True)
          .sign(ca_key, hashes.SHA256()))
    leaf = (certificate(leaf_name, ca_name, key.public_key())
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, None, None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("github.com")]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    ca_pem = ca.public_bytes(serialization.Encoding.PEM)
    leaf_pem = leaf.public_bytes(serialization.Encoding.PEM)
    (root / "ca.pem").write_bytes(ca_pem)
    (root / "server.pem").write_bytes(leaf_pem)
    (root / "chain.pem").write_bytes(leaf_pem + ca_pem)
    (root / "server.key").write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                                        serialization.PrivateFormat.PKCS8,
                                                        serialization.NoEncryption()))
    if WINDOWS:
        run("certutil", "-f", "-addstore", "Root", root / "ca.pem", capture_output=True)
    else:
        run("sudo", "security", "add-trusted-cert", "-d", "-r", "trustRoot", "-p", "ssl",
            "-k", "/Library/Keychains/System.keychain", root / "ca.pem")
        try:
            run("security", "verify-cert", "-c", root / "server.pem", "-p", "ssl", "-s", "github.com")
        except subprocess.CalledProcessError:
            # Constrain fallback to the exact one-day leaf on this disposable VM.
            run("sudo", "security", "add-trusted-cert", "-d", "-r", "trustAsRoot", "-p", "ssl",
                "-s", "github.com", "-k", "/Library/Keychains/System.keychain", root / "server.pem")
            run("security", "verify-cert", "-c", root / "server.pem", "-p", "ssl", "-s", "github.com")


def artifacts(path):
    with zipfile.ZipFile(path) as bundle:
        result = {Path(name).stem: hashlib.sha256(bundle.read(name)).hexdigest()
                  for name in bundle.namelist() if name.startswith("artifacts/")}
    assert result and all(name == value for name, value in result.items())
    return result


class Windows:
    def __init__(self, playwright, root, evidence):
        self.playwright = playwright
        self.profile = root / "webview"
        self.evidence = evidence

    def attach(self, pid):
        from smoke_windows_edit import debugger_url
        from urllib.request import urlopen

        self.pid = pid
        self.window = wait(lambda: visible_window(pid), "No visible Windows app")
        def endpoint():
            try:
                port = (self.profile / "EBWebView" / "DevToolsActivePort").read_text().splitlines()[0]
                with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as result:
                    return any("tauri.localhost" in t["url"] for t in json.load(result))
            except (OSError, ValueError, IndexError):
                return False
        wait(endpoint, "No active private WebView2 debugger after launch", timeout=45)
        browser = self.playwright.chromium.connect_over_cdp(debugger_url(self.profile), timeout=15000)
        self.page, = [page for context in browser.contexts for page in context.pages if "tauri.localhost" in page.url]
        self.page.set_default_timeout(15000)

    def button(self, name):
        return self.page.get_by_role("button", name=name, exact=True)

    def welcome(self):
        self.button("Edit a photo without AI").click()

    def input_file(self, path, *, save=False):
        from smoke_windows_edit import choose_file
        choose_file(self.pid, self.window, path, saving=save)

    def image(self, path):
        self.button("Attach images").click()
        self.input_file(path)

    def save(self, path):
        self.button("Save session").click()
        self.input_file(path.with_suffix(""), save=True)

    def panel(self):
        self.button("Settings").click()
        self.button("Updates").click()

    def check(self, version, candidate):
        self.button("Check for updates").click()
        self.page.get_by_text("Installed version: " + version, exact=True).wait_for()
        if candidate:
            self.page.get_by_text("Version 0.4.2 is available.", exact=True).wait_for()

    def attempt(self):
        self.button("Download & install update").click()

    def error(self, text):
        from playwright.sync_api import expect
        expect(self.page.get_by_role("alert")).to_contain_text(text, timeout=75000)

    def confirm(self):
        self.button("Save & close").wait_for(timeout=180000)
        self.shot("save-confirmation")
        self.button("Save & close").click()

    def reopen(self, path, count):
        self.button("Close settings").click()
        self.page.locator(".session-name").click()
        self.page.get_by_role("button", name=re.compile(r"^Open session")).click()
        self.input_file(path)
        self.page.get_by_text(re.compile(rf"\b{count} images\b")).wait_for()
        from smoke_windows_edit import viewer_hash
        return viewer_hash(self.page)

    def shot(self, name):
        self.page.screenshot(path=str(self.evidence / f"{name}.png"))


class Mac:
    def __init__(self, evidence):
        self.evidence = evidence

    def attach(self, pid):
        from AppKit import NSRunningApplication, NSApplicationActivateIgnoringOtherApps
        self.restarted = hasattr(self, "pid")
        self.pid = pid
        self.window = wait(lambda: visible_window(pid), "No visible macOS app")
        import Quartz as q
        print("macOS event posting authorized:", q.CGPreflightPostEventAccess(), flush=True)
        NSRunningApplication.runningApplicationWithProcessIdentifier_(pid).activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        self.shot("window-layout")
        with Image.open(self.evidence / "window-layout.png") as frame:
            self.size = frame.size

    def key(self, code, flags=0):
        import Quartz as q
        modifiers = [label for mask, label in (
            (q.kCGEventFlagMaskCommand, "command down"), (q.kCGEventFlagMaskShift, "shift down"),
        ) if flags & mask]
        using = " using {" + ", ".join(modifiers) + "}" if modifiers else ""
        run("osascript", "-e", f'tell application "System Events" to key code {code}{using}')

    def press(self, label):
        script = """
on run argv
    set targetPID to (item 1 of argv) as integer
    set wanted to item 2 of argv
    tell application "System Events"
        set proc to first application process whose unix id is targetPID
        set frontmost of proc to true
        repeat with element in entire contents of window 1 of proc
            try
                if role of element is "AXButton" then
                    set matches to false
                    try
                        set matches to name of element is wanted
                    end try
                    try
                        set matches to matches or description of element is wanted
                    end try
                    if matches then
                        perform action "AXPress" of element
                        return "pressed"
                    end if
                end if
            end try
        end repeat
    end tell
    return "missing"
end run
"""
        result = run("osascript", "-e", script, self.pid, label, text=True, capture_output=True)
        return result.stdout.strip() == "pressed"

    def click(self, x, y, frame):
        import Quartz as q
        windows = q.CGWindowListCopyWindowInfo(q.kCGWindowListOptionIncludingWindow, self.window)
        bounds = next(w["kCGWindowBounds"] for w in windows if w["kCGWindowNumber"] == self.window)
        pos = (bounds["X"] + x * bounds["Width"] / frame[0], bounds["Y"] + y * bounds["Width"] / frame[0])
        run("osascript", "-e", f'tell application "System Events" to click at {{{round(pos[0])}, {round(pos[1])}}}')

    def text(self, phrase, *, click=False, timeout=45, crop=None, exact=False, footer=False):
        import csv
        def probe():
            frame_path = self.evidence / "current.png"
            run("screencapture", "-x", "-o", "-l", self.window, frame_path)
            with Image.open(frame_path) as frame:
                size = frame.size
                shift_x, shift_y = (size[0] - 1024) // 2, (size[1] - 681) // 2
                bounds = tuple(n + (shift_y if i % 2 else shift_x) for i, n in enumerate(crop)) if crop else (0, 0, *size)
                if footer:
                    bounds = (size[0] // 2 - 160, size[1] - 26, size[0] // 2 + 160, size[1])
                img = frame.crop(bounds)
                img.resize((img.width * 2, img.height * 2)).save(self.evidence / "ocr.png")
            tsv = run("tesseract", self.evidence / "ocr.png", "stdout", "--psm", "7" if footer else "11", "tsv",
                      text=True, capture_output=True).stdout
            groups = {}
            for row in csv.DictReader(tsv.splitlines(), delimiter="\t"):
                if (row.get("text") or "").strip():
                    groups.setdefault(tuple(row[k] for k in ("block_num", "par_num", "line_num")), []).append(row)
            for words in groups.values():
                text = " ".join(word["text"] for word in words)
                if (phrase.casefold() == text.casefold() if exact else phrase.casefold() in text.casefold()):
                    w = next((w for w in words if phrase.casefold().startswith(w["text"].casefold())), words[0])
                    x = bounds[0] + int(w["left"]) / 2 + int(w["width"]) / 4
                    y = bounds[1] + int(w["top"]) / 2 + int(w["height"]) / 4
                    if click:
                        self.click(x, y, size)
                    print("UI:", text, flush=True)
                    return x, y
        return wait(probe, f"Missing visible Mac text {phrase!r}", timeout)

    def welcome(self):
        if not self.press("Start with a quick idea"):
            self.key(36)

    def image(self, path):
        from AppKit import NSPasteboard, NSPasteboardTypePNG
        from Foundation import NSData
        import Quartz as q
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        assert pasteboard.setData_forType_(NSData.dataWithContentsOfFile_(str(path)), NSPasteboardTypePNG)
        self.key(9, q.kCGEventFlagMaskCommand)

    def navigate(self, path):
        import Quartz as q
        self.key(5, q.kCGEventFlagMaskCommand | q.kCGEventFlagMaskShift)
        time.sleep(1.1)
        run("pbcopy", input=str(path).encode())
        self.key(9, q.kCGEventFlagMaskCommand)
        time.sleep(.65)
        self.key(36)
        time.sleep(1.3)

    def open_path(self, path):
        self.navigate(path)
        if not self.press("Open"):
            self.key(36)

    def save(self, path):
        import Quartz as q
        if not self.press("Save session"):
            self.key(1, q.kCGEventFlagMaskCommand)
        x, y = self.text("Where", crop=(325, 190, 675, 610), timeout=45)
        self.shot("save-dialog-open")
        self.click(x + 145, y - 74, self.size)
        run("pbcopy", input=path.stem.encode())
        self.key(0, q.kCGEventFlagMaskCommand)
        self.key(9, q.kCGEventFlagMaskCommand)
        time.sleep(.6)
        self.shot("save-filename-entered")
        self.navigate(path.parent)
        self.text(path.parent.name, crop=(350, 190, 675, 610), timeout=15)
        self.shot("save-dialog-directory")
        self.key(36)
        time.sleep(1.5)
        if not path.is_file() and not self.press("Save"):
            x, y = self.text("Where", crop=(325, 190, 675, 610), timeout=12)
            self.click(x + 290, y + 42, self.size)
        time.sleep(.7)
        self.shot("save-dialog-submitted")
        print("Save folder files:", [x.name for x in path.parent.iterdir()], flush=True)

    def panel(self):
        wait(lambda: self.press("Settings"), "Accessible Settings button unavailable")
        if not self.press("Updates"):
            self.text("Updates", click=True, exact=True)

    def check(self, version, candidate):
        if candidate:
            self.text("0.4.2 is available")
        else:
            if not self.press("Check for updates"):
                self.text("Check for updates", click=True, crop=(258, 150, 515, 370))
        self.text("Installed version: " + version, crop=(245, 135, 918, 625))

    def attempt(self):
        if not self.press("Download & install update"):
            self.text("install update", click=True, crop=(264, 150, 918, 625))

    def error(self, text):
        self.text(text, timeout=75, crop=(264, 150, 918, 625))

    def confirm(self):
        self.text("Save changes", timeout=180, crop=(242, 250, 782, 575))
        self.shot("save-confirmation")
        if not self.press("Save & close"):
            width, height = self.size
            self.click(width / 2 + 192, (height - 681) / 2 + 393, self.size)

    def reopen(self, path, count):
        import Quartz as q
        if not self.press("Close settings"):
            width, height = self.size
            self.click(width / 2 + 370, (height - 681) / 2 + 107, self.size)
        self.key(31, q.kCGEventFlagMaskCommand)
        time.sleep(.8)
        self.open_path(path)
        self.press("Open")
        self.text(f"{count} images", footer=True)

    def shot(self, name):
        run("screencapture", "-x", "-o", "-l", self.window, self.evidence / f"{name}.png")


def main(old, asset, root, evidence):
    assert os.environ.get("GITHUB_ACTIONS") == "true", "Hosted upgrade needs a disposable runner"
    evidence.mkdir(exist_ok=True)
    root.mkdir()
    certificate(root)
    shutil.copyfile(Path(__file__).with_name("latest.json"), asset.parent / "latest.json")
    feed = StagedFeed(root, asset.parent, asset.name)
    executable = install(old, root / "installed")
    nonce = secrets.token_hex(12)
    ready = root / "ready.json"
    env = {**os.environ, **{key: str(root / key.lower()) for key in (
        "BADSHOP_CONFIG_DIR", "BADSHOP_DATA_DIR", "BADSHOP_LOG_DIR", "BADSHOP_OUT")},
        "HTTPS_PROXY": feed.url, "https_proxy": feed.url, "SSL_CERT_FILE": str(root / "ca.pem"),
        "NO_PROXY": "127.0.0.1,localhost,tauri.localhost", "no_proxy": "127.0.0.1,localhost,tauri.localhost",
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

    def launch():
        log = (evidence / "app.log").open("ab")
        try:
            return subprocess.Popen([str(executable)], env=env, stdout=log, stderr=subprocess.STDOUT)
        finally:
            log.close()

    def gone(process):
        try:
            return not process.is_running() or process.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return True

    project = root / "upgrade-fixture.badshop"
    initial = None
    updated = None
    with contextlib.ExitStack() as stack:
        if WINDOWS:
            from playwright.sync_api import sync_playwright
            from smoke_windows_edit import runner_webview_policy
            stack.enter_context(runner_webview_policy(executable, root / "webview"))
            ui = Windows(stack.enter_context(sync_playwright()), root, evidence)
        else:
            ui = Mac(evidence)
            for key in ("BADSHOP_CONFIG_DIR", "BADSHOP_DATA_DIR", "BADSHOP_LOG_DIR", "BADSHOP_OUT",
                        "HTTPS_PROXY", "https_proxy", "SSL_CERT_FILE", "NO_PROXY", "no_proxy",
                        "BADSHOP_SMOKE_READY_FILE", "BADSHOP_SMOKE_NONCE"):
                run("launchctl", "setenv", key, env[key])
                stack.callback(run, "launchctl", "unsetenv", key)
        try:
            initial = launch()
            start = wait(state, "0.4.1 packaged core did not connect", timeout=120)
            ui.attach(start["shell_pid"])
            ui.shot("initial")
            if start["welcome"]:
                ui.welcome()
                wait(lambda: (s := state()) and not s["welcome"], "Welcome did not dismiss")

            def import_color(color):
                path = root / f"picture-{color[0]}.png"
                Image.new("RGBA", (60, 45), color).save(path)
                ui.image(path)
                wait(lambda: (s := state()) and s["unsaved"], "Import did not dirty project")

            import_color((15, 90, 150, 255))
            ui.save(project)
            wait(project.is_file, "Native Save As did not write the project")
            wait(lambda: (s := state()) and not s["unsaved"], "Project stayed dirty after Save As")
            before = digest(project)
            original_artifacts = artifacts(project)
            shutil.copyfile(project, evidence / "pre-upgrade.badshop")
            import_color((230, 75, 12, 255))
            print("Project after second import:", digest(project), "Saved baseline:", before, flush=True)
            ui.panel()
            ui.check("0.4.1", True)
            children = psutil.Process(start["shell_pid"]).children(recursive=True)
            assert any(is_core(child) for child in children)
            old_exe = digest(executable)
            for mode, expected in (("interrupt", "error decoding response body"), ("tampered", "signature verification failed")):
                feed.mode = mode
                ui.attempt()
                ui.error(expected)
                ui.shot(mode)
                assert state()["shell_pid"] == start["shell_pid"]
                current_exe, current_project = digest(executable), digest(project)
                print("Rejected update digests:", mode, current_exe, old_exe, current_project, before, flush=True)
                assert current_exe == old_exe and current_project == before

            feed.mode = "valid"
            ui.attempt()
            ui.confirm()
            def restarted():
                if (new := state()) and new["shell_pid"] != start["shell_pid"]:
                    return new
                if WINDOWS:
                    for process in psutil.process_iter(["pid", "exe"]):
                        if (process.pid != start["shell_pid"] and process.info["exe"]
                                and Path(process.info["exe"]).resolve() == executable
                                and visible_window(process.pid)):
                            print("Restarted Windows shell inherited the WebView policy, but not the test marker", flush=True)
                            return {"shell_pid": process.pid}

            try:
                updated = wait(restarted, "Installed app did not restart into a ready window", timeout=100)
            except AssertionError:
                print("Installer or application processes:", [
                    (p.pid, p.info["name"], p.info["exe"])
                    for p in psutil.process_iter(["name", "exe"])
                    if p.info["name"] and any(n in p.info["name"].lower() for n in ("badshop", "setup", "nsis"))
                ], flush=True)
                print("Installed shell digest:", digest(executable), "Before:", old_exe, flush=True)
                if WINDOWS:
                    from PIL import ImageGrab
                    ImageGrab.grab(all_screens=True).save(evidence / "restart-timeout.png")
                raise
            assert digest(executable) != old_exe
            wait(lambda: all(gone(child) for child in children if is_core(child)), "Old core or worker survived")
            after = digest(project)
            saved_artifacts = artifacts(project)
            shutil.copyfile(project, evidence / "post-upgrade.badshop")
            assert after != before and original_artifacts.items() < saved_artifacts.items()
            ui.attach(updated["shell_pid"])
            if WINDOWS:
                ui.page.get_by_text("Connected", exact=True).wait_for()
            ui.panel()
            ui.check("0.4.2", False)
            ui.shot("updated")
            shown = ui.reopen(project, len(saved_artifacts))
            if shown:
                assert shown in saved_artifacts
            assert digest(project) == after
            ui.shot("recovered")
            (evidence / "summary.json").write_text(json.dumps({
                "status": "passed", "platform": platform.platform(), "version": "0.4.2",
                "restart": True, "old_core_cleanup": True, "project_before": before,
                "project_after": after, "artifact_hashes": saved_artifacts, "requests": feed.requests,
                "old_installer_sha256": digest(old), "new_updater_sha256": digest(asset),
            }, indent=2))
        finally:
            if project.is_file():
                shutil.copyfile(project, evidence / "last-project.badshop")
            if hasattr(ui, "window"):
                with contextlib.suppress(Exception):
                    ui.shot("last")
            for pid in {s["shell_pid"] for s in (state(), updated) if s} | ({initial.pid} if initial else set()):
                with contextlib.suppress(psutil.NoSuchProcess):
                    shell = psutil.Process(pid)
                    descendants = shell.children(recursive=True)
                    shell.terminate()
                    _, living = psutil.wait_procs([shell, *descendants], timeout=15)
                    for process in living:
                        with contextlib.suppress(psutil.NoSuchProcess):
                            process.kill()
            feed.server.shutdown()


if __name__ == "__main__":
    main(*(Path(x).resolve() for x in sys.argv[1:]))
