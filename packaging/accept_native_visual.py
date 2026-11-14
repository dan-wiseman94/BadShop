"""Read labels from real native screenshots and click them on private CI desktops."""
import csv
import io
import re
import subprocess
import sys
import time

from PIL import Image
from native_windows import screenshot


class NativeLabels:
    def __init__(self, window, output):
        self.window, self.output = window, output

    def read(self):
        shot = self.output / 'native-labels.png'
        screenshot(self.window, shot)
        ocr = self.output / 'native-labels-ocr.png'
        with Image.open(shot) as image:
            # Remove light control borders that otherwise merge small button labels.
            image.convert('L').point(lambda value: 0 if value < 120 else 255).resize(
                (image.width * 3, image.height * 3), Image.Resampling.NEAREST).save(ocr)
        result = subprocess.check_output(['tesseract', str(ocr), 'stdout', '--psm', '11', 'tsv'],
                                         stderr=subprocess.DEVNULL, text=True, timeout=20)
        (self.output / 'native-labels.tsv').write_text(result)
        rows = [r for r in csv.DictReader(io.StringIO(result), delimiter='\t') if r['text'].strip()]
        return rows, shot

    def wait(self, label, timeout=45, click=False):
        expected = [re.sub(r'[^\w]', '', word) for word in label.lower().split()]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rows, shot = self.read()
            words = [re.sub(r'[^\w]', '', row['text'].lower()) for row in rows]
            for index in range(len(words) - len(expected) + 1):
                if words[index:index + len(expected)] == expected:
                    row = rows[index]
                    if click:
                        x = (int(row['left']) + int(row['width']) / 2) / 3
                        y = (int(row['top']) + int(row['height']) / 2) / 3
                        if sys.platform == 'darwin':
                            import Quartz
                            windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionIncludingWindow,
                                                                       self.window)
                            bounds = windows[0]['kCGWindowBounds']
                            with Image.open(shot) as image:
                                x = bounds['X'] + x * bounds['Width'] / image.width
                                y = bounds['Y'] + y * bounds['Height'] / image.height
                            for kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
                                event = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), Quartz.kCGMouseButtonLeft)
                                Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
                        else:
                            subprocess.run(['xdotool', 'windowfocus', '--sync', str(self.window),
                                            'mousemove', '--window', str(self.window), str(round(x)), str(round(y)),
                                            'click', '1'], check=True, timeout=5)
                    screenshot(self.window, self.output / (re.sub(r'\W+', '-', label) + '.png'))
                    return
            time.sleep(.5)
        raise AssertionError(f'Native screen did not show {label!r}; see native-labels.png/tsv')

    def click(self, label, timeout=45):
        self.wait(label, timeout=timeout, click=True)
