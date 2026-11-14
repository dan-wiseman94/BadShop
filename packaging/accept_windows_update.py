"""Exercise an installed Windows updater using real signed candidate bytes."""
import contextlib
import hashlib
import json
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import psutil
from playwright.sync_api import expect, sync_playwright

from accept_update_server import UpdateServer
from native_windows import normal_close, visible_window
from smoke_desktop import smoke
from smoke_windows_edit import choose_file, debugger_url, runner_webview_policy, smoke_editing, viewer_hash


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upgrade(executable, candidate, root, output, fixture):
    expected_executable = digest(executable)
    core_executable, = executable.parent.rglob('badshop-core.exe')
    expected_core = digest(core_executable)
    candidate_installer, = candidate.glob('*.exe')
    expected_installer = digest(candidate_installer)
    baseline = root / 'baseline'
    baseline.mkdir()
    subprocess.run(['gh', 'release', 'download', 'v0.4.3', '--pattern', '*x64-setup.exe',
                    '--dir', str(baseline)], check=True, timeout=300)
    installer, = baseline.glob('*.exe')
    subprocess.run([str(installer), '/S', '/D=' + str(executable.parent)], check=True, timeout=180)
    old_executable = digest(executable)
    assert old_executable != expected_executable
    smoke_editing(executable, output / 'baseline.png', fixture, baseline, material_panel=False)
    project = baseline / 'native-edit.badshop'
    project_bytes = digest(project)
    backup = baseline / 'backup.badshop'
    shutil.copyfile(project, backup)
    baseline_summary = json.loads((output / 'summary.json').read_text())
    image_hash = baseline_summary['output_sha256']
    profile = root / 'update-webview'
    summary = {'status': 'failed', 'checks': [], 'project_sha256_before': project_bytes}

    def reopen(path, name, *, reject_future=False):
        reopened_profile = root / (name + '-webview')

        def verify(pid, window, close):
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(debugger_url(reopened_profile), timeout=15000)
                page, = [p for c in browser.contexts for p in c.pages if p.url.startswith('http://tauri.localhost')]
                page.get_by_role('button', name='Edit a photo without AI', exact=True).click()
                page.locator('.session-name').click()
                page.get_by_role('button', name=re.compile(r'^Open session')).click()
                choose_file(pid, window, path)
                if reject_future:
                    expect(page.get_by_role('alert').filter(has_text='newer badshop')).to_be_visible(timeout=20000)
                else:
                    assert viewer_hash(page) == image_hash
                page.screenshot(path=str(output / (name + '.png')))
                close()

        with runner_webview_policy(executable, reopened_profile):
            smoke([str(executable)], output / (name + '-native.png'),
                  webview_profile=reopened_profile, exercise=verify)

    def exercise(pid, window, close):
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(debugger_url(profile), timeout=15000)
            page, = [p for c in browser.contexts for p in c.pages if p.url.startswith('http://tauri.localhost')]
            page.set_default_timeout(30000)
            page.context.tracing.start(screenshots=True, snapshots=True)
            try:
                page.get_by_role('button', name='Edit a photo without AI', exact=True).click()
                page.locator('.session-name').click()
                page.get_by_role('button', name=re.compile(r'^Open session')).click()
                choose_file(pid, window, project)
                assert viewer_hash(page) == image_hash
                page.get_by_role('button', name='Settings', exact=True).click()
                page.get_by_role('button', name='Updates', exact=True).click()
                page.get_by_role('button', name='Check for updates', exact=True).click()
                expect(page.get_by_text('Installed version: 0.4.3', exact=True)).to_be_visible()
                version = json.loads((candidate / 'latest.json').read_text())['version']
                expect(page.get_by_text(f'Version {version} is available.', exact=True)).to_be_visible()
                button = page.get_by_role('button', name='Download & install update', exact=True)
                button.click()
                expect(page.get_by_role('alert').filter(has_text='Could not install update')).to_be_visible(timeout=90000)
                assert digest(executable) == old_executable
                page.screenshot(path=str(output / 'update-interrupted.png'))
                summary['checks'].append('interrupted download rejected without changing installed executable')
                server.mode = 'tampered'
                button.click()
                expect(page.get_by_role('alert').filter(has_text=re.compile('signature', re.I))).to_be_visible(timeout=120000)
                assert digest(executable) == old_executable
                page.screenshot(path=str(output / 'update-tampered.png'))
                summary['checks'].append('tampered payload rejected by installed signature verification')
                server.mode = 'authentic'
                children = psutil.Process(pid).children(recursive=True)
                install_started = time.time()
                button.click()
                page.wait_for_event('close', timeout=180000)
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    with contextlib.suppress(OSError):
                        if digest(executable) == expected_executable:
                            break
                    time.sleep(.5)
                else:
                    raise AssertionError('Authentic update did not install the expected executable')
                # NSIS replaces the shell before extracting the much larger core.
                # Do not launch or close the new app while extraction is in flight.
                for process in psutil.process_iter(['name', 'exe', 'create_time']):
                    if (process.info['name'] == f'badshop-{version}-installer.exe'
                            and process.info['create_time'] >= install_started - 1):
                        assert digest(Path(process.info['exe'])) == expected_installer
                        assert process.wait(timeout=180) == 0, 'Updater installer failed'
                assert digest(core_executable) == expected_core, 'Updated core differs from candidate'
                _, alive = psutil.wait_procs(children, timeout=30)
                assert not alive, f'Old app children survived: {alive}'
                summary['checks'].append('authentic signed update installed exact candidate executable; old children exited')
            finally:
                with contextlib.suppress(Exception):
                    page.context.tracing.stop(path=output / 'updater.zip')

    try:
        with UpdateServer(candidate, root, output) as server, runner_webview_policy(executable, profile):
            smoke([str(executable)], output / 'update.png', webview_profile=profile, exercise=exercise)
            # Close only the updater-launched instance from this temporary install.
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                matches = []
                for process in psutil.process_iter(['exe']):
                    with contextlib.suppress(psutil.Error):
                        if process.info['exe'] and Path(process.info['exe']).resolve() == executable.resolve():
                            matches.append(process)
                if matches:
                    for process in matches:
                        window = visible_window(process.pid)
                        if window:
                            normal_close(process.pid, window)
                            process.wait(timeout=30)
                    break
                time.sleep(.5)
        assert digest(project) == project_bytes, 'Update changed the saved project bytes'
        reopen(project, 'upgraded-project')
        summary['project_sha256_after'] = digest(project)
        summary['checks'].append('saved project bytes retained and candidate reopened identical rendered pixels')
        subprocess.run([str(installer), '/S', '/D=' + str(executable.parent)], check=True, timeout=180)
        assert digest(executable) == old_executable
        reopen(backup, 'rollback-backup')
        future = baseline / 'newer-format.badshop'
        with zipfile.ZipFile(backup) as source, zipfile.ZipFile(future, 'w') as target:
            for member in source.infolist():
                data = source.read(member)
                if member.filename == 'session.json':
                    value = json.loads(data)
                    value['schema'] = 999
                    data = json.dumps(value).encode()
                target.writestr(member, data)
        future_hash = digest(future)
        reopen(future, 'rollback-newer-rejected', reject_future=True)
        assert digest(future) == future_hash
        assert digest(backup) == project_bytes
        summary['checks'].append('rollback reopened backup pixels and refused to modify a newer schema')
        subprocess.run([str(candidate_installer), '/S', '/D=' + str(executable.parent)], check=True, timeout=180)
        assert digest(executable) == expected_executable
        summary['status'] = 'passed'
    finally:
        (output / 'windows-update.json').write_text(json.dumps(summary, indent=2))
