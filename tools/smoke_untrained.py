"""Architecture/build smoke ONLY. Random weights; never a compression benchmark."""
import json
from pathlib import Path
import sys
import tempfile
import time
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'vendor' / 'DCVC'))


def main():
    import torch
    import demo.codec as adapter
    from demo.engine import synthetic_frame
    from src.models.image_model import DMCI
    from src.models.video_model_ht import DMC
    from src.utils.common import ModelStructure
    torch.manual_seed(42)
    torch.set_num_threads(2)
    with tempfile.TemporaryDirectory(prefix='dcvc-untrained-') as directory:
        folder = Path(directory)
        print('UNTRAINED ARCHITECTURE SMOKE; not official model performance.', flush=True)
        torch.save(DMCI().state_dict(), folder / 'cvpr2026_image.pth.tar')
        torch.save(DMC(model_structure=ModelStructure.HTS).state_dict(), folder / 'cvpr2026_video_hts.pth.tar')
        adapter.CHECKPOINTS = folder
        encoder, decoder = adapter.Codec(), adapter.Codec()
        records = []
        index = 0
        for count in (1, 8, 8):
            frames = [synthetic_frame(640, 360, index+i) for i in range(count)]
            index += count
            packet = encoder.encode(frames, 32)
            restored = decoder.decode(packet)
            assert len(restored) == count
            assert all(frame.shape == (360, 640, 3) and str(frame.dtype) == 'uint8' for frame in restored)
            records.append({'type': packet[0]['type'], 'count': count, 'bytes': len(packet[1]), 'ec': packet[0]['ec']})
            print(records[-1], flush=True)
        heartbeat, ticks = threading.Event(), []
        def monitor():
            while not heartbeat.wait(.001):
                ticks.append(time.monotonic())
        thread = threading.Thread(target=monitor)
        torch.cuda.set_stream(encoder.stream)
        x = torch.zeros(1, 3, 360, 640, dtype=torch.float16, device='cuda').to(memory_format=torch.channels_last)
        thread.start()
        before = time.monotonic()
        encoder.i.proxy.compress(x, 32, 8, 0)
        after = time.monotonic()
        heartbeat.set()
        thread.join()
        active_ticks = sum(before < tick < after for tick in ticks)
        if after - before > .01:
            assert active_ticks > 1, 'Native inference held the Python GIL'
        result = {'scope': 'UNTRAINED random-weight architecture smoke. No pretrained quality/FPS acceptance.',
                  'status': 'passed', 'records': records, 'torch': torch.__version__,
                  'native_call_ms': (after - before) * 1000, 'heartbeat_ticks_during_native': active_ticks}
        (ROOT / 'reports' / 'untrained-smoke.json').write_text(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
