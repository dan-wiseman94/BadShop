import hashlib
import json
import shutil
import sys
from pathlib import Path

root, destination = map(Path, sys.argv[1:3])
name, expected = sys.argv[3:]
asset, = root.rglob(name)
with asset.open('rb') as stream:
    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
assert actual == expected, (name, actual, expected)
feed = json.loads(Path(__file__).with_name('latest.json').read_text())
entry, = [value for value in feed['platforms'].values() if value['url'].endswith('/' + name)]
assert entry['signature'] == Path(str(asset) + '.sig').read_text().strip()
destination.mkdir(parents=True)
shutil.copyfile(asset, destination / name)
print(f'Verified exact release asset and feed signature: {name} {actual}')
