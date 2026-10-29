"""Hardware regression: repeated real HT-S start/pause/end must release tensors."""
import json
from pathlib import Path
import sys
import time
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cycles', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.cycles <= 100:
        parser.error('cycles must be between 1 and 100')
    import torch
    from demo.engine import Engine
    from demo.config import Settings
    engine, records = Engine(), []
    try:
        for cycle in range(args.cycles):
            engine.start(Settings())
            deadline = time.monotonic() + 60
            while engine.snapshot()['decode']['frames'] < 17:
                snapshot = engine.snapshot()
                if snapshot['state'] == 'error':
                    raise RuntimeError(snapshot['message'])
                if time.monotonic() > deadline:
                    raise TimeoutError('Model did not decode the test frames')
                time.sleep(.02)
            snapshot = engine.snapshot()
            engine.pause() if cycle == 1 else engine.stop()
            deadline = time.monotonic() + 20
            while engine.alive() and time.monotonic() < deadline:
                time.sleep(.02)
            assert not engine.alive(), 'Worker did not release its resources'
            allocated = torch.cuda.memory_allocated()
            records.append({'cycle': cycle, 'decoded': snapshot['decode']['frames'],
                            'cuda_allocated_after_end': allocated, 'state': engine.snapshot()['state']})
            print(records[-1], flush=True)
            assert allocated < 16 * 1024 * 1024, 'Native pool retained tensors after stop'
        (ROOT / 'reports' / 'restart-check.json').write_text(json.dumps({'status': 'passed', 'records': records}, indent=2))
    finally:
        engine.stop()


if __name__ == '__main__':
    main()
