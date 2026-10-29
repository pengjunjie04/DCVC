"""Sequential independent GPU processes: genuine wire bytes, untrained weights only."""
import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'vendor' / 'DCVC'))


class FileConnection:
    def __init__(self, source=None, destination=None):
        self.source, self.destination = source, destination
    def recv(self, size):
        return self.source.read(size)
    def sendall(self, data):
        self.destination.write(data)


def worker(directory, role):
    import demo.codec as adapter
    from demo.engine import synthetic_frame
    from demo.transport import send_packet
    from demo.receiver import handle_connection
    folder = Path(directory)
    adapter.CHECKPOINTS = folder
    codec = adapter.Codec()
    if role == 'encode':
        with (folder / 'stream.bin').open('wb') as stream:
            connection = FileConnection(destination=stream)
            index = 0
            for count in (1, 8, 8):
                packet = codec.encode([synthetic_frame(640, 360, index+i) for i in range(count)], 32)
                send_packet(connection, *packet)
                print(f'encoded {count} frames into {len(packet[1])} bytes', flush=True)
                index += count
    else:
        with (folder / 'stream.bin').open('rb') as stream, (folder / 'previews.bin').open('wb') as previews:
            try:
                handle_connection(FileConnection(stream, previews), codec)
            except EOFError:
                pass


def main():
    import torch
    from demo.transport import recv_packet, decode_preview
    from src.models.image_model import DMCI
    from src.models.video_model_ht import DMC
    from src.utils.common import ModelStructure
    parser = argparse.ArgumentParser()
    parser.add_argument('--pretrained', action='store_true')
    args = parser.parse_args()
    torch.manual_seed(42)
    torch.set_num_threads(2)
    with tempfile.TemporaryDirectory(prefix='dcvc-independent-smoke-') as directory:
        folder = Path(directory)
        label = 'PRETRAINED' if args.pretrained else 'UNTRAINED'
        print(label + ' sequential independent-process correctness smoke; not performance acceptance', flush=True)
        if args.pretrained:
            for name in ('cvpr2026_image.pth.tar', 'cvpr2026_video_hts.pth.tar'):
                (folder / name).symlink_to(ROOT / 'checkpoints' / name)
        else:
            torch.save(DMCI().state_dict(), folder / 'cvpr2026_image.pth.tar')
            torch.save(DMC(model_structure=ModelStructure.HTS).state_dict(), folder / 'cvpr2026_video_hts.pth.tar')
        for role in ('encode', 'decode'):
            child = multiprocessing.get_context('spawn').Process(target=worker, args=(directory, role))
            child.start()
            child.join(120)
            if child.is_alive():
                child.terminate()
                child.join(5)
                raise RuntimeError(f'{role} timed out')
            assert child.exitcode == 0, (role, child.exitcode)
        records = []
        with (folder / 'previews.bin').open('rb') as previews:
            connection = FileConnection(source=previews)
            for count in (1, 8, 8):
                meta, data = recv_packet(connection)
                frames, elapsed = decode_preview(meta, data, count, 640, 360)
                records.append({'frames': len(frames), 'preview_bytes': len(data)})
        result = {'scope': label + ' independent encoder and decoder processes, serialized genuine wire frames, sequential on one Jetson to fit memory; not dual-device performance acceptance',
                  'status': 'passed', 'records': records}
        name = 'pretrained-independent-process-smoke.json' if args.pretrained else 'independent-process-smoke.json'
        (ROOT / 'reports' / name).write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
