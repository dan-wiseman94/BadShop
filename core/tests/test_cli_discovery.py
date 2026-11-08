"""GUI CLI discovery with a restricted PATH and isolated installation folders."""

import os
from pathlib import Path

import pytest

from badshop.providers import cli_provider


@pytest.fixture
def windows_install(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_provider.sys, "platform", "win32")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(cli_provider.shutil, "which", lambda _: None)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))

    def install(relative, modified=100):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
        path.chmod(0o700)
        os.utime(path, (modified, modified))
        return str(path)

    return install


def test_windows_codex_desktop_discovery_without_path(windows_install):
    windows_install("Local/OpenAI/Codex/bin/old/codex.exe", 100)
    newest = windows_install("Local/OpenAI/Codex/bin/new/codex.exe", 200)
    windows_install("Local/OpenAI/Codex/bin/other-tool/rg.exe", 300)
    assert cli_provider.find_executable("codex") == newest
    assert cli_provider.find_executable("claude") is None


@pytest.mark.parametrize("cli", ["claude", "codex", "gemini"])
def test_windows_npm_discovery_without_path(windows_install, cli):
    npm = windows_install(f"Roaming/npm/{cli}.cmd")
    assert cli_provider.find_executable(cli) == npm


def test_discovery_preserves_explicit_and_path_priority(windows_install, monkeypatch):
    desktop = windows_install("Local/OpenAI/Codex/bin/current/codex.exe")
    npm = windows_install("Roaming/npm/codex.cmd")
    assert cli_provider.find_executable("codex") == npm
    on_path = windows_install("custom/codex.exe")
    monkeypatch.setattr(cli_provider.shutil, "which", lambda _: on_path)
    assert cli_provider.find_executable("codex") == on_path
    assert cli_provider.find_executable("codex", desktop) == desktop
    if os.name == "nt":
        assert cli_provider.find_executable("codex", f'"{desktop}"') == desktop
    assert cli_provider.find_executable("codex", desktop + ".missing") is None


def test_missing_windows_cli_reports_not_found(windows_install):
    info = cli_provider.inspect_cli("codex")
    assert not info["available"] and not info["supported"]
    assert "codex was not found" in info["error"]


@pytest.mark.skipif(os.name == "nt", reason="Unix executable contract; run in the Linux task worktree")
@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_unix_gui_discovery_keeps_user_bin(windows_install, monkeypatch, platform):
    monkeypatch.setattr(cli_provider.sys, "platform", platform)
    native = windows_install("home/.local/bin/codex")
    windows_install("Local/OpenAI/Codex/bin/current/codex.exe")
    assert cli_provider.find_executable("codex") == native


@pytest.mark.parametrize("app", ["ChatGPT.app/Contents/Resources/codex-cli/bin", "Codex.app/Contents/Resources"])
def test_macos_codex_desktop_discovery_without_path(windows_install, monkeypatch, app):
    monkeypatch.setattr(cli_provider.sys, "platform", "darwin")
    bundled = windows_install(f"home/Applications/{app}/codex")
    assert cli_provider.find_executable("codex") == bundled
