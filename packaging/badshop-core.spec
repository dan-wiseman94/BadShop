# PyInstaller onedir: large native runtimes stay unpacked alongside the core.
import os
from pathlib import Path
from importlib.metadata import distributions
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
root = Path(SPECPATH).parent
binaries, datas, hidden = [], [], []
for package in ('badshop', 'rembg', 'onnxruntime', 'keyring', 'mcp'):
    d, b, h = collect_all(package, filter_submodules=lambda n: not n.startswith(('mcp.cli', 'rembg.cli')))
    datas += d
    binaries += b
    hidden += h
# LiteLLM dynamically imports provider adapters; omit its unrelated API gateway.
hidden += collect_submodules('litellm', filter=lambda n: not n.startswith(('litellm.proxy', 'litellm.integrations')))
datas += collect_data_files('litellm')
datas += collect_data_files('cv2')
for dist in distributions():
    try:
        datas += copy_metadata(dist.metadata['Name'])
    except Exception:
        pass

a = Analysis([str(root / 'packaging/frozen_entry.py')], pathex=[str(root / 'core/src')],
             binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=['tkinter', 'IPython', 'notebook', 'matplotlib', 'torch', 'tensorflow', 'pytest'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='badshop-core',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='badshop-core')
