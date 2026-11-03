"""Verify the two official HT-S checkpoint files before running the model."""
import argparse
import hashlib
from pathlib import Path


EXPECTED = {
    'cvpr2026_image.pth.tar': {
        'bytes': 168845375,
        'sha256': 'b3b900de23f30e4fc437010ddffe6a5413a56d6cfd97fb6235adbcd2b6973302',
    },
    'cvpr2026_video_hts.pth.tar': {
        'bytes': 324891626,
        'sha256': '565607d84943ee79072a5760d34a200d5724b4bb72c6bc24bfab41e8ae4f5f47',
    },
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoints', type=Path, default=Path(__file__).resolve().parents[1] / 'checkpoints')
    args = parser.parse_args()
    failed = False
    for name, expected in EXPECTED.items():
        path = args.checkpoints / name
        if not path.is_file():
            print(f'MISSING  {path}')
            failed = True
            continue
        size = path.stat().st_size
        digest = sha256(path)
        if size != expected['bytes'] or digest != expected['sha256']:
            print(f'INVALID  {path}')
            print(f'         size={size} expected={expected["bytes"]}')
            print(f'         sha256={digest}')
            print(f'         expected={expected["sha256"]}')
            failed = True
        else:
            print(f'OK       {path}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
