"""Benchmark genuine HT-S bitstreams. No preview, pacing, or simulated codec."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from demo.codec import Codec, readiness
from demo.engine import synthetic_frame, letterbox


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--groups', type=int, default=20)
    parser.add_argument('--qp', type=int, default=32)
    parser.add_argument('--output', default='reports/benchmark.json')
    parser.add_argument('--input-video', help='Optional prerecorded clip; file reading is excluded from codec timing')
    args = parser.parse_args()
    if args.groups < 3 or not 0 <= args.qp <= 63:
        parser.error('groups >= 3，QP 为 0–63')
    problems = readiness()
    if problems:
        print('\n'.join(problems))
        return 2
    reader, video_info = None, None
    if args.input_video:
        import cv2
        reader = cv2.VideoCapture(args.input_video)
        if not reader.isOpened():
            raise RuntimeError('无法读取测试视频')
        video_info = {'path': args.input_video, 'source_fps': reader.get(cv2.CAP_PROP_FPS),
                      'source_width': reader.get(cv2.CAP_PROP_FRAME_WIDTH), 'source_height': reader.get(cv2.CAP_PROP_FRAME_HEIGHT)}
    encoder, decoder = Codec(), Codec()
    import numpy as np
    totals = {'encode_s': 0., 'decode_s': 0., 'frames': 0, 'bytes': 0, 'mse_sum': 0.}
    index = 0
    for group in range(args.groups + 3):
        count = 1 if group == 0 else 8
        if reader is None:
            source = [synthetic_frame(640, 360, index + i) for i in range(count)]
        else:
            source = []
            for _ in range(count):
                ok, frame = reader.read()
                if not ok:
                    raise RuntimeError('测试视频帧数不足，请降低 --groups')
                source.append(letterbox(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), 640, 360))
        index += count
        before = time.monotonic()
        packet = encoder.encode(source, args.qp)
        encoded = time.monotonic()
        output = decoder.decode(packet)
        done = time.monotonic()
        if len(output) != count or any(frame.shape != (360, 640, 3) for frame in output):
            raise RuntimeError('解码帧数或尺寸错误')
        if group >= 3:
            totals['encode_s'] += encoded - before
            totals['decode_s'] += done - encoded
            totals['frames'] += count
            totals['bytes'] += len(packet[1])
            totals['mse_sum'] += sum(float(np.mean((a.astype(float) - b.astype(float)) ** 2)) for a,b in zip(source, output))
        print(f'group={group} frames={count} bytes={len(packet[1])} encode_ms={(encoded-before)*1000:.2f} decode_ms={(done-encoded)*1000:.2f}', flush=True)
    if reader is not None:
        reader.release()
    result = {**totals, 'encode_fps': totals['frames'] / totals['encode_s'],
              'decode_fps': totals['frames'] / totals['decode_s'],
              'content_mbps_at_30fps': totals['bytes'] * 8 / (totals['frames'] / 30) / 1e6,
              'scope': '640x360 ' + ('prerecorded clip' if video_info else 'generated moving pattern') + ', real bitstream, independent states, same Jetson, 3 warmup groups excluded; not dual-host acceptance; content Mbps assumes 30fps rather than source timing',
              'input_video': video_info,
              'qp': args.qp}
    Path(args.output).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
