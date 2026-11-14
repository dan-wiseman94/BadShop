"""Signed installed-app upgrade and rollback on macOS and Linux AppImage."""
import contextlib
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

import psutil

from accept_native_visual import NativeLabels
from accept_update_server import UpdateServer
from native_windows import normal_close, visible_window
from smoke_desktop import linux_file_dialog, native_keys, smoke, wait_saved_project


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def open_existing(pid, window, project, output, *, reject_future=False):
    if sys.platform == 'darwin':
        from accept_native_macos import open_existing as mac_open
        mac_open(pid, window, project, output, reject_future=reject_future)
        return
    ready = Path(psutil.Process(pid).environ()['BADSHOP_SMOKE_READY_FILE'])
    if json.loads(ready.read_text())['welcome']:
        native_keys(window, 'Return')
        time.sleep(1)
    native_keys(window, 'ctrl+o')
    linux_file_dialog(pid, window, project)
    if reject_future:
        NativeLabels(window, output).wait('newer badshop')
    else:
        with zipfile.ZipFile(project) as source:
            identity = json.loads(source.read('session.json'))['id']
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            state = json.loads(ready.read_text())
            if state['session_id'] == identity and not state['unsaved']:
                break
            time.sleep(.2)
        else:
            raise AssertionError('AppImage did not reopen expected project')
        wait_saved_project(ready.parent / 'core-data/autosave/session.badshop', project)


def upgrade(candidate, root, output, label, installed_app=None):
    assert os.environ.get('GITHUB_ACTIONS') == 'true'
    baseline = root / 'update-baseline'
    baseline.mkdir()
    pattern = f'badshop-{label}.app.tar.gz' if sys.platform == 'darwin' else '*.AppImage'
    subprocess.run(['gh', 'release', 'download', 'v0.4.3', '--dir', str(baseline), '--pattern', pattern],
                   check=True, timeout=300)
    baseline_output = output / 'update-baseline'
    baseline_output.mkdir()
    if sys.platform == 'darwin':
        backup_app = root / 'candidate-backup.app'
        installed_app.rename(backup_app)
        archive, = baseline.glob('*.app.tar.gz')

        def install_baseline():
            if installed_app.exists():
                shutil.rmtree(installed_app)
            with tarfile.open(archive) as source:
                source.extractall(baseline, filter='data')
            app, = baseline.glob('*.app')
            app.rename(installed_app)

        install_baseline()
        info = plistlib.loads((installed_app / 'Contents/Info.plist').read_bytes())
        relative = Path('Contents/MacOS') / info['CFBundleExecutable']
        executable = installed_app / relative
        expected_hash = digest(backup_app / relative)
        old_hash = digest(executable)
        from accept_native_macos import editing
        smoke([str(executable)], baseline_output / 'native.png',
              exercise=lambda pid, window, close: editing(pid, window, close, baseline_output))
        project = baseline_output / 'mac-native-project.badshop'
    else:
        original, = candidate.glob('*.AppImage')
        old, = baseline.glob('*.AppImage')
        executable = root / 'updatable.AppImage'

        def install_baseline():
            # FUSE can retain the executed inode after its window closes. Replace
            # the path atomically, as AppImage installation does, rather than
            # truncating an executable inode (ETXTBSY on Linux).
            staged = executable.with_suffix('.replacement')
            shutil.copyfile(old, staged)
            staged.chmod(0o755)
            staged.replace(executable)

        install_baseline()
        expected_hash, old_hash = digest(original), digest(executable)
        smoke([str(executable)], baseline_output / 'native.png', restart_core=True)
        project = baseline_output / 'native-native-recovered.badshop'
    assert old_hash != expected_hash
    project_hash = digest(project)
    backup = baseline_output / 'project-backup.badshop'
    shutil.copyfile(project, backup)
    summary = {'status': 'failed', 'checks': [], 'project_sha256_before': project_hash}

    def exercise(pid, window, close):
        open_existing(pid, window, project, output)
        labels = NativeLabels(window, output)
        labels.click('Review update', timeout=60)
        labels.wait('Installed version: 0.4.3')
        labels.click('Download')
        labels.wait('Could not install update', timeout=90)
        assert digest(executable) == old_hash
        summary['checks'].append('interrupted download rejected without installing')
        server.mode = 'tampered'
        labels.click('Download')
        labels.wait('signature', timeout=180)
        assert digest(executable) == old_hash
        summary['checks'].append('tampered payload rejected by installed signature verifier')
        server.mode = 'authentic'
        children = psutil.Process(pid).children(recursive=True)
        labels.click('Download')
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            with contextlib.suppress(OSError):
                if digest(executable) == expected_hash:
                    break
            time.sleep(.5)
        else:
            raise AssertionError('Authentic update did not install expected candidate')
        _, alive = psutil.wait_procs(children, timeout=30)
        assert not alive, f'Old core/WebView children survived: {alive}'
        summary['checks'].append('authentic signed candidate installed; old children exited')

    def reopen(path, name, reject_future=False):
        def verify(pid, window, close):
            open_existing(pid, window, path, output, reject_future=reject_future)
            close()
        smoke([str(executable)], output / (name + '.png'), exercise=verify)

    try:
        with UpdateServer(candidate, root, output) as server:
            # update_install restarts through Tauri, not the native Quit menu.
            # The callback verifies the installed hash and old process cleanup.
            smoke([str(executable)], output / 'update.png', exercise=exercise, exit_via_update=True)
            # Identify only the restarted instance of this temporary installation.
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                closed = False
                for process in psutil.process_iter(['exe']):
                    with contextlib.suppress(psutil.Error):
                        owned = (process.info['exe'] == str(executable) if sys.platform == 'darwin'
                                 else process.environ().get('APPIMAGE') == str(executable))
                        if owned and (window := visible_window(process.pid)):
                            normal_close(process.pid, window)
                            process.wait(timeout=30)
                            closed = True
                if closed:
                    break
                time.sleep(.5)
        reopen(project, 'upgraded-project')
        assert digest(project) == project_hash
        summary['checks'].append('candidate reopened saved project pixels without modifying saved bytes')
        install_baseline()
        assert digest(executable) == old_hash
        reopen(backup, 'rollback-backup')
        future = baseline_output / 'future.badshop'
        with zipfile.ZipFile(backup) as source, zipfile.ZipFile(future, 'w') as target:
            for member in source.infolist():
                data = source.read(member)
                if member.filename == 'session.json':
                    value = json.loads(data)
                    value['schema'] = 999
                    data = json.dumps(value).encode()
                target.writestr(member, data)
        future_hash = digest(future)
        reopen(future, 'rollback-future-rejected', reject_future=True)
        assert digest(future) == future_hash and digest(backup) == project_hash
        summary['checks'].append('rollback reopened backup pixels; newer schema rejected unchanged')
        if sys.platform == 'darwin':
            shutil.rmtree(installed_app)
            backup_app.rename(installed_app)
        summary['status'] = 'passed'
    finally:
        (output / 'posix-update.json').write_text(json.dumps(summary, indent=2))
