"""Measure an offered rembg model under the same worker limits used by the app."""
import argparse
import io
import json
import os
from pathlib import Path

from badshop.engine import manifest
from badshop.session.session import Session
from badshop.session.worker import WorkerExecutor
from PIL import Image


class MeasuredWorker(WorkerExecutor):
    peak_mb = 0.0

    def _rss_mb(self):
        rss = super()._rss_mb()
        self.peak_mb = max(self.peak_mb, rss)
        return rss


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', default='birefnet-general')
    p.add_argument('--memory-mb', type=int, default=8192)
    p.add_argument('--data-dir', type=Path)
    args = p.parse_args()
    if args.data_dir:
        os.environ['BADSHOP_DATA_DIR'] = str(args.data_dir.resolve())
    manifest.download(f'rembg/{args.model}.onnx')
    worker = MeasuredWorker(timeout_s=600, max_rss_mb=args.memory_mb)
    try:
        session = Session.new(executor=worker)
        fixture = Path(__file__).resolve().parent.parent / 'core/tests/fixtures/lincoln.png'
        with Image.open(fixture) as image, io.BytesIO() as out:
            image.resize((761, 1000), Image.Resampling.NEAREST).save(out, 'PNG')
            artifact = session.import_image(out.getvalue(), 'model-measurement')
        result = session.run_tool('cutout', {'image': artifact.id, 'model': args.model}, 'user')
        print(json.dumps({'model': args.model, 'input_size': [761, 1000], 'peak_rss_mb': round(worker.peak_mb, 1),
                          'status': result.status, 'error': result.error.model_dump() if result.error else None}))
        return 0 if result.status == 'done' else 1
    finally:
        worker.close()


if __name__ == '__main__':
    raise SystemExit(main())
