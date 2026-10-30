"""Opt-in wired quality regression on a prerecorded clip; never records camera images."""
import argparse
import glob
import json
import math
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-video', default=str(ROOT/'tools/testdata/vtest.avi'))
    parser.add_argument('--bind', default='192.168.50.1')
    parser.add_argument('--peer', default='192.168.50.2')
    parser.add_argument('--port', type=int, default=9860)
    parser.add_argument('--groups', type=int, default=33)
    parser.add_argument('--qp', type=int, default=32)
    parser.add_argument('--min-psnr', type=float, default=30.)
    parser.add_argument('--output', default=str(ROOT/'reports/quality-check.json'))
    args = parser.parse_args()
    if args.groups < 2 or not 0 <= args.qp <= 63:
        parser.error('groups >= 2, QP 0–63')
    import cv2
    import numpy as np
    from demo.codec import Codec
    from demo.engine import letterbox
    from demo.transport import ethernet_route, send_packet, recv_packet, decode_preview
    ethernet_route(args.bind, args.peer)
    initial = {p:int(Path(p).read_text()) for p in glob.glob('/sys/class/hwmon/hwmon*/oc*_event_cnt')}
    report = {'scope':'Prerecorded clip -> genuine HT-S -> wired independent decoder -> JPEG75. RGB PSNR includes preview JPEG. Not camera FPS or paper-quality acceptance. No video or images saved.',
              'input':args.input_video, 'qp':args.qp, 'groups':[], 'minimum_required_psnr':args.min_psnr}
    reader = cv2.VideoCapture(args.input_video)
    codec = None
    try:
        if not reader.isOpened():
            raise RuntimeError('无法读取测试视频')
        codec = Codec()
        report['encoder_runtime'] = codec.runtime
        with socket.socket() as sock:
            sock.settimeout(180)
            sock.bind((args.bind,0)); sock.connect((args.peer,args.port))
            for group in range(args.groups):
                if any(int(Path(p).read_text())>n for p,n in initial.items()):
                    raise RuntimeError('新增过流事件，停止测试')
                count = 1 if group == 0 else 8
                frames = []
                for _ in range(count):
                    ok, frame = reader.read()
                    if not ok:
                        raise RuntimeError('测试视频帧数不足')
                    frames.append(letterbox(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB),640,360))
                packet = codec.encode(frames,args.qp)
                packet[0]['fps'] = 30
                send_packet(sock,*packet)
                meta,data = recv_packet(sock)
                decoded,_ = decode_preview(meta,data,count,640,360)
                frame_mse = [float(np.mean((a.astype(np.float32)-b.astype(np.float32))**2)) for a,b in zip(frames,decoded)]
                psnr = [10*math.log10(255**2/max(m,1e-10)) for m in frame_mse]
                row = {'group':group,'frames':count,'psnr_rgb':10*math.log10(255**2/max(float(np.mean(frame_mse)),1e-10)),
                       'min_frame_psnr':min(psnr),'bytes':len(packet[1])}
                report['groups'].append(row)
                print(json.dumps(row),flush=True)
        report['minimum_frame_psnr'] = min(g['min_frame_psnr'] for g in report['groups'])
        if report['minimum_frame_psnr'] < args.min_psnr:
            raise RuntimeError(f'画质低于设定门槛：{report["minimum_frame_psnr"]:.2f}dB < {args.min_psnr:.2f}dB')
        report['status'] = 'passed'
        return 0
    except Exception as exc:
        report.update(status='failed',error=str(exc))
        raise
    finally:
        reader.release()
        if codec is not None:
            codec.close()
        report['overcurrent_before'] = initial
        report['overcurrent_after'] = {p:int(Path(p).read_text()) for p in initial}
        path = Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    raise SystemExit(main())
