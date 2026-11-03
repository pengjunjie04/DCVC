"""Compare DCVC-RT HT-S with Jetson hardware H.264/H.265 on one public clip.

Run with the system Python because GStreamer's Python bindings live outside the
project environment. The script never opens a camera and saves only statistics.
"""
import argparse
import glob
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT, FPS = 640, 360, 30
WARMUP_FRAMES = 1 + 2 * 8


def psnr_from_mse(mse):
    if mse <= 0:
        return float('inf')
    return 10 * math.log10(255 ** 2 / mse)


def interpolate_log_bitrate(points, target_psnr):
    ordered = sorted(points, key=lambda item:item['psnr_db'])
    for lower, upper in zip(ordered, ordered[1:]):
        if lower['psnr_db'] <= target_psnr <= upper['psnr_db']:
            span = upper['psnr_db'] - lower['psnr_db']
            fraction = 0 if span == 0 else (target_psnr - lower['psnr_db']) / span
            bitrate = math.exp(math.log(lower['bitrate_kbps']) +
                               fraction * (math.log(upper['bitrate_kbps']) - math.log(lower['bitrate_kbps'])))
            return {'bitrate_kbps':bitrate, 'target_psnr_db':target_psnr,
                    'lower_bitrate_kbps':lower['bitrate_kbps'],
                    'upper_bitrate_kbps':upper['bitrate_kbps'],
                    'lower_psnr_db':lower['psnr_db'], 'upper_psnr_db':upper['psnr_db']}
    return None


def hardware_quality_points(rows, codec):
    return [{'bitrate_kbps':row['actual_kbps'], 'psnr_db':row['psnr_db']}
            for row in rows if row['codec'] == codec]


def overcurrent_counts():
    return {path:int(Path(path).read_text()) for path in glob.glob('/sys/class/hwmon/hwmon*/oc*_event_cnt')}


def check_overcurrent(initial):
    current = overcurrent_counts()
    if any(current.get(path, count) > count for path, count in initial.items()):
        raise RuntimeError('新增过流事件，停止对比测试')
    return current


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda:stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def prepare_frames(input_video, output_i420, output_bgr, frames, warmup=WARMUP_FRAMES):
    import cv2
    import numpy as np
    reader = cv2.VideoCapture(str(input_video))
    if not reader.isOpened():
        raise RuntimeError('无法读取测试视频')
    try:
        with open(output_i420, 'wb') as i420, open(output_bgr, 'wb') as bgr:
            for index in range(warmup + frames):
                ok, frame = reader.read()
                if not ok:
                    raise RuntimeError(f'测试视频不足 {warmup + frames} 帧')
                if index < warmup:
                    continue
                height, width = frame.shape[:2]
                scale = min(WIDTH / width, HEIGHT / height)
                new_width, new_height = max(1, round(width * scale)), max(1, round(height * scale))
                fitted = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
                top, left = (HEIGHT - new_height) // 2, (WIDTH - new_width) // 2
                fitted[top:top+new_height, left:left+new_width] = cv2.resize(frame, (new_width, new_height))
                i420.write(cv2.cvtColor(fitted, cv2.COLOR_BGR2YUV_I420))
                bgr.write(fitted.tobytes())
    finally:
        reader.release()


def run_gstreamer(description, start_name, start_pad, end_name, end_pad,
                  expected_input, expected_output, timeout=180):
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst
    Gst.init(None)
    pipeline = Gst.parse_launch(description)
    state = {'input':0, 'output':0, 'start_ns':None, 'end_ns':None}

    def on_start(pad, info, user_data):
        state['input'] += 1
        if state['start_ns'] is None:
            state['start_ns'] = time.monotonic_ns()
        return Gst.PadProbeReturn.OK

    def on_end(pad, info, user_data):
        state['output'] += 1
        state['end_ns'] = time.monotonic_ns()
        return Gst.PadProbeReturn.OK

    start_element = pipeline.get_by_name(start_name)
    end_element = pipeline.get_by_name(end_name)
    if start_element is None or end_element is None:
        pipeline.set_state(Gst.State.NULL)
        raise RuntimeError('GStreamer 管线缺少探针元素')
    start_element.get_static_pad(start_pad).add_probe(Gst.PadProbeType.BUFFER, on_start, None)
    end_element.get_static_pad(end_pad).add_probe(Gst.PadProbeType.BUFFER, on_end, None)

    pipeline.set_state(Gst.State.PLAYING)
    bus = pipeline.get_bus()
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            message = bus.timed_pop_filtered(remaining * Gst.MSECOND,
                                             Gst.MessageType.EOS | Gst.MessageType.ERROR)
            if message is None:
                raise TimeoutError('GStreamer 管线超时')
            if message.type == Gst.MessageType.ERROR:
                error, debug = message.parse_error()
                raise RuntimeError(f'GStreamer 错误：{error.message}；{debug or ""}')
            if message.type == Gst.MessageType.EOS:
                break
    finally:
        pipeline.set_state(Gst.State.NULL)
    if state['input'] != expected_input:
        raise RuntimeError(f'输入帧数错误：{state["input"]} != {expected_input}')
    if state['output'] != expected_output:
        raise RuntimeError(f'输出帧数错误：{state["output"]} != {expected_output}')
    if state['start_ns'] is None or state['end_ns'] is None or state['end_ns'] <= state['start_ns']:
        raise RuntimeError('GStreamer 探针未取得有效计时')
    return {'frames':expected_output, 'elapsed_s':(state['end_ns'] - state['start_ns']) / 1e9}


def encode_hardware(codec, bitrate_kbps, raw_i420, bitstream, frames):
    parser = 'h264parse' if codec == 'h264' else 'h265parse'
    description = (
        f'filesrc location={raw_i420} ! rawvideoparse width={WIDTH} height={HEIGHT} '
        f'format=i420 framerate={FPS}/1 ! nvvidconv ! '
        f'capsfilter name=nvmm caps="video/x-raw(memory:NVMM),format=I420" ! '
        f'nvv4l2{codec}enc name=codec bitrate={int(bitrate_kbps * 1000)} '
        f'control-rate=constant_bitrate preset-level=1 iframeinterval=30 ! '
        f'{parser} ! filesink name=sink location={bitstream}'
    )
    return run_gstreamer(description, 'codec', 'sink', 'codec', 'src', frames, frames)


def decode_hardware(codec, bitstream, frames, output_bgrx=None):
    parser = 'h264parse' if codec == 'h264' else 'h265parse'
    sink = f'filesink name=sink location={output_bgrx}' if output_bgrx else 'fakesink name=sink sync=false'
    description = (
        f'filesrc location={bitstream} ! {parser} ! nvv4l2decoder name=decoder ! nvvidconv ! '
        f'capsfilter name=out caps="video/x-raw,format=BGRx" ! {sink}'
    )
    return run_gstreamer(description, 'decoder', 'sink', 'out', 'src', frames, frames)


def raw_psnr(reference_bgr, decoded_bgrx, frames):
    import numpy as np
    reference = np.memmap(reference_bgr, dtype=np.uint8, mode='r').reshape(frames, HEIGHT, WIDTH, 3)
    decoded = np.memmap(decoded_bgrx, dtype=np.uint8, mode='r').reshape(frames, HEIGHT, WIDTH, 4)
    squared_error = 0.
    for start in range(0, frames, 16):
        stop = min(frames, start + 16)
        diff = reference[start:stop].astype(np.int16) - decoded[start:stop, :, :, :3].astype(np.int16)
        squared_error += float(np.square(diff, dtype=np.float64).sum())
    mse = squared_error / (frames * WIDTH * HEIGHT * 3)
    return psnr_from_mse(mse), mse


def run_dcvc(args, input_video, frames, output_path, cudnn_dir):
    env = os.environ.copy()
    env['PYTHONNOUSERSITE'] = '1'
    env['PYTHONPATH'] = str(ROOT)
    if cudnn_dir and Path(cudnn_dir, 'libcudnn.so.9').exists():
        env['LD_LIBRARY_PATH'] = cudnn_dir + (':' + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    command = [str(ROOT / args.dcvc_python), '-s', str(ROOT / 'tools/benchmark.py'),
               '--groups', str(frames // 8), '--qp', str(args.qp), '--input-video', str(input_video),
               '--output', str(output_path)]
    subprocess.run(command, cwd=ROOT, env=env, check=True)
    result = json.loads(Path(output_path).read_text())
    result['psnr_db'] = psnr_from_mse(result['mse_sum'] / result['frames'])
    result['actual_kbps'] = result['bytes'] * 8 / (result['frames'] / FPS) / 1000
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-video', default=str(ROOT / 'tools/testdata/vtest.avi'))
    parser.add_argument('--frames', type=int, default=640)
    parser.add_argument('--qp', type=int, default=32)
    parser.add_argument('--bitrates', default='32,64,128,256,512',
                        help='Hardware CBR targets in kbps')
    parser.add_argument('--dcvc-python', default='.env/bin/python')
    parser.add_argument('--require-power-mode', default='25W')
    parser.add_argument('--temp-dir', default='/tmp')
    parser.add_argument('--output', default=str(ROOT / 'reports/codec-comparison-25w.json'))
    args = parser.parse_args()
    if args.frames < 64 or args.frames % 8:
        parser.error('frames 必须为不小于 64 的 8 的倍数')
    bitrates = []
    for value in args.bitrates.split(','):
        value = value.strip()
        if not value:
            continue
        parsed = int(value)
        if parsed <= 0:
            parser.error('码率必须为正整数')
        bitrates.append(parsed)
    if not bitrates:
        parser.error('至少指定一个码率')
    input_video = Path(args.input_video).resolve()
    if not input_video.is_file():
        parser.error('找不到输入视频')
    if not (ROOT / args.dcvc_python).is_file():
        parser.error('找不到 DCVC Python 环境')
    power_mode = subprocess.check_output(['nvpmodel', '-q'], text=True).strip()
    if args.require_power_mode and ('NV Power Mode: ' + args.require_power_mode) not in power_mode:
        raise RuntimeError('当前功耗模式不符合要求：' + power_mode)
    initial_oc = overcurrent_counts()
    cudnn_dir = os.environ.get('DCVC_CUDNN_LIB_DIR', str(Path.home() / '.cache/dcvc-runtime/cudnn-9.20'))
    required_bytes = args.frames * WIDTH * HEIGHT * (3 / 2 + 3 + 4) + 256 * 1024 * 1024
    if shutil.disk_usage(args.temp_dir).free < required_bytes:
        raise RuntimeError('临时目录空间不足，停止测试')
    report = {
        'scope':'Public vtest.avi only; same 640x360 BGR reference, same Orin NX and 25W, sequential runs; no camera images or video saved. Hardware encode timing excludes process startup via pad probes and includes JPEG-free BGRx conversion only for quality decode; decode speed uses fakesink. DCVC is a local single-process independent encoder/decoder pair with three warmup groups excluded.',
        'input':{'path':str(input_video), 'sha256':sha256_file(input_video), 'source_fps':10.,
                 'playback_fps':FPS, 'width':WIDTH, 'height':HEIGHT, 'frames':args.frames,
                 'warmup_frames':WARMUP_FRAMES},
        'power_mode':power_mode, 'overcurrent_before':initial_oc,
        'hardware':[], 'dcvc':None, 'matched_quality':{},
    }
    with tempfile.TemporaryDirectory(prefix='dcvc-codec-compare-', dir=args.temp_dir) as directory:
        temp = Path(directory)
        i420 = temp / 'reference.i420'
        reference = temp / 'reference.bgr'
        print('preparing reference frames', flush=True)
        prepare_frames(input_video, i420, reference, args.frames)
        check_overcurrent(initial_oc)
        print('running DCVC', flush=True)
        dcvc = run_dcvc(args, input_video, args.frames, temp / 'dcvc.json', cudnn_dir)
        report['dcvc'] = {key:dcvc.get(key) for key in
                          ('encode_fps', 'decode_fps', 'actual_kbps', 'bytes', 'frames', 'psnr_db', 'qp', 'encode_s', 'decode_s')}
        check_overcurrent(initial_oc)
        for codec in ('h264', 'h265'):
            for bitrate in bitrates:
                bitstream = temp / f'{codec}-{bitrate}.bit'
                decoded = temp / f'{codec}-{bitrate}.bgrx'
                print(f'running {codec} {bitrate} kbps', flush=True)
                encoded = encode_hardware(codec, bitrate, i420, bitstream, args.frames)
                checked = check_overcurrent(initial_oc)
                decoded_speed = decode_hardware(codec, bitstream, args.frames)
                checked = check_overcurrent(initial_oc)
                decode_hardware(codec, bitstream, args.frames, decoded)
                psnr, mse = raw_psnr(reference, decoded, args.frames)
                size = bitstream.stat().st_size
                row = {'codec':codec.upper(), 'target_kbps':bitrate,
                       'actual_kbps':size * 8 / (args.frames / FPS) / 1000,
                       'psnr_db':psnr, 'mse':mse, 'bytes':size,
                       'encode_s':encoded['elapsed_s'], 'decode_s':decoded_speed['elapsed_s'],
                       'encode_fps':args.frames / encoded['elapsed_s'],
                       'decode_fps':args.frames / decoded_speed['elapsed_s'],
                       'overcurrent':checked}
                report['hardware'].append(row)
                print(json.dumps({key:row[key] for key in
                                  ('codec', 'target_kbps', 'actual_kbps', 'psnr_db', 'encode_fps', 'decode_fps')},
                                 ensure_ascii=False), flush=True)
                decoded.unlink()
    for codec in ('H264', 'H265'):
        points = hardware_quality_points(report['hardware'], codec)
        matched = interpolate_log_bitrate(points, report['dcvc']['psnr_db'])
        if matched is not None:
            report['matched_quality'][codec] = matched
    report['overcurrent_after'] = check_overcurrent(initial_oc)
    report['status'] = 'passed'
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status':report['status'], 'dcvc':report['dcvc'],
                      'matched_quality':report['matched_quality']}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
