"""Paste BadShop's actual OS image clipboard into a separate Chromium window."""
import base64
import io
import json
import sys
import subprocess
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright


def paste_into_browser(expected_png, output):
    # Windows calls this while its WebView driver already owns a Playwright loop.
    # A separate recipient process also models an independent target application.
    expected = output / 'clipboard-expected.png'
    expected.write_bytes(expected_png)
    subprocess.run([sys.executable, __file__, str(expected), str(output)], check=True, timeout=90)


def receive(expected_png, output):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False, args=['--no-sandbox'])
        try:
            page = browser.new_page()
            page.set_content('''<!doctype html><meta charset="utf-8">
              <h1>Native image clipboard recipient</h1>
              <div id="editor" contenteditable="true" style="min-height:300px;border:1px solid">Paste here</div>
              <script>document.addEventListener('paste', async event => {
                const file = [...event.clipboardData.files].find(f => f.type.startsWith('image/'));
                if (!file) return;
                const reader = new FileReader(); reader.onload = () => { window.received = reader.result;
                  const image = document.createElement('img'); image.src = reader.result;
                  document.body.append(image); }; reader.readAsDataURL(file);
              });</script>''')
            page.locator('#editor').click()
            page.keyboard.press('Meta+V' if sys.platform == 'darwin' else 'Control+V')
            page.wait_for_function('typeof window.received === "string"', timeout=20000)
            received = base64.b64decode(page.evaluate('window.received').split(',', 1)[1])
            actual = Image.open(io.BytesIO(received)).convert('RGBA')
            expected = Image.open(io.BytesIO(expected_png)).convert('RGBA')
            assert actual.size == expected.size and actual.tobytes() == expected.tobytes()
            (output / 'clipboard-received.png').write_bytes(received)
            page.screenshot(path=str(output / 'clipboard-browser.png'))
            (output / 'clipboard.json').write_text(json.dumps({'status': 'passed', 'target': 'Chromium',
                'method': 'native paste into contenteditable; clipboardData image decoded',
                'width': actual.width, 'height': actual.height, 'rgba_equal': True}, indent=2))
        finally:
            browser.close()


if __name__ == '__main__':
    receive(Path(sys.argv[1]).read_bytes(), Path(sys.argv[2]))
