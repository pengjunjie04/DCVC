"""Decoder-local monitor: JPEG-only parent process, no additional CUDA model."""
from collections import deque
import json
import math
from pathlib import Path
import statistics
import threading
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from .engine import LatestFrames
from .metrics import ProcessingStats, WindowStats

ROOT = Path(__file__).resolve().parents[1]
# Every displayed frame must stay under the 500 ms software-latency target. The
# budget is measured when the burst arrives, before browser fetch/decode/draw, so
# it sits below 500 ms to leave room for that final hop.
DISPLAY_BUDGET_MS = 478


class DecoderMonitor:
    def __init__(self):
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.exit_requested = threading.Event()
        self.queue = LatestFrames(limit=16)
        self.jpeg = None
        self.capture_mono = None
        self.seq = self.epoch = 0
        self.draw_samples = deque(maxlen=1800)
        self.state, self.message = 'waiting', '等待编码端连接；请在第一台点击开始'
        self.settings = {'mode':'send', 'width':640, 'height':360, 'fps':30, 'qp':32}
        self.hardware = None
        self._reset_rates()
        self.player = threading.Thread(target=self._play, daemon=True)
        self.player.start()

    def _reset_rates(self):
        self.decode = WindowStats()
        self.preview = WindowStats()
        self.processing = {name:ProcessingStats() for name in ('encode', 'decode')}
        self.ipc_dropped = 0
        self.stale_dropped = 0
        self.trim_dropped = 0
        self.encode_fps = 0.
        self.last_oldest_age_ms = None
        self.totals = {'frames':0, 'bytes':0, 'encode_ms':0., 'decode_ms':0.}
        self.draw_samples.clear()

    def begin_session(self):
        with self.lock:
            self.epoch += 1
            self._reset_rates()
            self.state, self.message = 'starting', '连接已建立，正在加载解码模型和首组画面'
            with self.queue.changed:
                self.queue.items.clear()
                self.queue.dropped = 0

    def accept(self, info, previews):
        capture_ages = info.get('capture_ages_ns')
        if capture_ages is None:
            capture_ages = [None] * len(previews)
        if (not isinstance(capture_ages, list) or len(capture_ages) != len(previews) or
                any(value is not None and (type(value) is not int or value < 0)
                    for value in capture_ages)):
            raise ValueError('解码预览的采集年龄无效')
        # Convert the encoder-side age into a decoder-local monotonic capture time.
        # Monotonic time cannot be stepped by NTP, so a clock correction on this
        # board cannot make a stale frame look fresh.
        now_mono = time.monotonic()
        capture_times = [None if age is None else now_mono - age / 1e9 for age in capture_ages]
        with self.lock:
            self.settings = {name:info[name] for name in ('width','height','fps','qp')} | {'mode':'send'}
            frames = info['total_frames'] - self.totals['frames']
            size = info['total_bytes'] - self.totals['bytes']
            self.decode.add(frames=frames, size=size)
            for name in ('encode','decode'):
                key = name + '_ms'
                elapsed = info[key] - self.totals[key] if info.get(key) is not None else None
                self.processing[name].add(frames, elapsed)
            self.totals = {'frames':info['total_frames'], 'bytes':info['total_bytes'],
                           'encode_ms':info.get('encode_ms') or 0., 'decode_ms':info['decode_ms']}
            self.encode_fps = info.get('encode_fps', 0.)
            self.ipc_dropped += max(0, frames - len(previews))
            self.state, self.message = 'running', '正在第二台解码并显示 · 编码速度由第一台实时传入'
            # HT-S delivers eight frames at once. Play them at the capture cadence
            # instead of a 60 fps burst, which reads as a stutter followed by a gap.
            display_fps = max(1, self.settings['fps'])
            # Pacing preserves each frame's age, so a burst that is already late would
            # stay late for its whole playback. Skip its oldest frames instead: every
            # remaining frame is then displayed at the budgeted age.
            budget_ns = int(DISPLAY_BUDGET_MS * 1e6)
            skip = 0
            if capture_times and capture_times[0] is not None:
                oldest_age = time.monotonic() - capture_times[0]
                if oldest_age * 1e9 > budget_ns:
                    skip = min(len(previews) - 1,
                               math.ceil((oldest_age * 1e9 - budget_ns) / (1e9 / display_fps)))
            self.trim_dropped += skip
            self.last_oldest_age_ms = max(0., (time.monotonic() - capture_times[0]) * 1000) if capture_times[0] is not None else None
            for jpeg, capture_ns in zip(previews[skip:], capture_times[skip:]):
                self.queue.put((self.epoch, jpeg, display_fps, capture_ns))
            self.queue.trim(max(10, len(previews) + 2))

    def end_session(self, code):
        with self.lock:
            self.state = 'waiting' if code == 0 else 'error'
            self.message = '会话已结束，保留最后画面；等待编码端再次开始' if code == 0 else f'解码会话退出（{code}），等待下一次连接'
            self.encode_fps = 0.

    def _play(self):
        deadline = time.monotonic()
        budget_ns = int(DISPLAY_BUDGET_MS * 1e6)
        while not self.closed.is_set():
            items = self.queue.take(1, self.closed)
            if not items:
                return
            epoch, jpeg, fps, capture_ns = items[0]
            now = time.monotonic()
            if now > deadline + 1 / fps:
                deadline = now
            if self.closed.wait(max(0, deadline - now)):
                return
            # Check the age at the moment of display: a backlog left by a slow
            # stretch is skipped instead of being shown late.
            if capture_ns is not None and (time.monotonic() - capture_ns) * 1e9 > budget_ns:
                with self.lock:
                    self.trim_dropped += 1
                deadline = time.monotonic()
                continue
            with self.lock:
                if epoch != self.epoch:
                    deadline += 1 / fps
                    continue
                self.jpeg, self.seq, self.capture_mono = jpeg, self.seq + 1, capture_ns
                self.preview.add(frames=1)
            deadline += 1 / fps

    def record_draws(self, samples, dropped=0):
        accepted = 0
        with self.lock:
            self.stale_dropped += dropped
            current = self.seq
            for item in samples:
                if not isinstance(item, list) or len(item) != 3:
                    continue
                sequence, capture_us, draw_us = item
                if any(type(value) is not int or value <= 0 for value in item):
                    continue
                if not 0 < sequence <= current or sequence < current - 120:
                    continue
                latency_us = draw_us - capture_us
                if not 0 <= latency_us <= 120_000_000:
                    continue
                self.draw_samples.append({'sequence':sequence, 'capture_unix_us':capture_us,
                                          'draw_unix_us':draw_us, 'latency_ms':latency_us / 1000})
                accepted += 1
        return accepted

    def latency_summary(self):
        with self.lock:
            values = sorted(sample['latency_ms'] for sample in self.draw_samples)
        if not values:
            return {'count':0, 'median_ms':None, 'p95_ms':None, 'min_ms':None, 'max_ms':None}
        return {'count':len(values), 'median_ms':statistics.median(values),
                'p95_ms':values[math.ceil(len(values) * .95) - 1],
                'min_ms':values[0], 'max_ms':values[-1]}

    def latency_report(self):
        with self.lock:
            return {'summary':self.latency_summary(), 'samples':list(self.draw_samples)}

    def snapshot(self):
        with self.lock:
            decode = self.decode.snapshot()
            latency = self.latency_summary()
            hardware = self.hardware.snapshot() if self.hardware is not None else None
            return {'role':'decoder', 'state':self.state, 'message':self.message,
                    'settings':dict(self.settings), 'capture':{'fps':0},
                    'encode':{'fps':self.encode_fps if decode['fps'] else 0., 'mbps':decode['mbps']},
                    'decode':decode, 'preview':self.preview.snapshot(),
                    'processing':{key:value.snapshot() for key,value in self.processing.items()},
                    'timing':{'capture_to_canvas_median_ms':latency['median_ms'],
                              'capture_to_canvas_p95_ms':latency['p95_ms'],
                              'capture_to_canvas_max_ms':latency['max_ms'],
                              'capture_to_canvas_samples':latency['count']},
                    'display_queue':len(self.queue.items),
                    'display_oldest_age_ms':self.last_oldest_age_ms,
                    'dropped':0, 'preview_dropped':self.queue.dropped + self.ipc_dropped + self.stale_dropped + self.trim_dropped,
                    'hardware':hardware}

    def image(self):
        with self.lock:
            # Report the age against the wall clock at serve time; the age itself
            # came from monotonic clocks on both hosts.
            capture_ns = (None if self.capture_mono is None else
                          time.time_ns() - int((time.monotonic() - self.capture_mono) * 1e9))
            return self.seq, self.jpeg, capture_ns

    def export(self):
        path = ROOT / 'runs' / f'decoder-report-{time.time_ns()}.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2))
        return str(path)

    def close(self):
        self.closed.set()
        self.player.join(timeout=1)

    def attach_hardware(self, hardware):
        with self.lock:
            self.hardware = hardware

    def hardware_frame(self, codec):
        hardware = self.hardware
        return hardware.frame(codec) if hardware is not None else None


def create_decoder_app(monitor, mount_ui=True):
    api = FastAPI(title='视频解码端')

    @api.get('/api/state')
    def state():
        return monitor.snapshot()

    @api.get('/api/frame/decoded')
    def frame(after: int = -1):
        seq, jpeg, capture_ns = monitor.image()
        if jpeg is None or seq == after:
            return Response(status_code=204, headers={'Cache-Control':'no-store'})
        headers = {'X-Sequence':str(seq), 'Cache-Control':'no-store'}
        if capture_ns is not None:
            headers['X-Capture-Unix-Ns'] = str(capture_ns)
        return Response(jpeg, media_type='image/jpeg', headers=headers)

    @api.get('/api/frame/{kind}')
    def hardware_frame(kind: str, after: int = -1):
        if kind not in ('h264', 'h265'):
            raise HTTPException(404)
        item = monitor.hardware_frame(kind)
        if item is None:
            return Response(status_code=204, headers={'Cache-Control':'no-store'})
        sequence, capture_ns, jpeg = item
        if sequence == after:
            return Response(status_code=204, headers={'Cache-Control':'no-store'})
        return Response(jpeg, media_type='image/jpeg',
                        headers={'X-Sequence':str(sequence), 'Cache-Control':'no-store',
                                 'X-Capture-Unix-Ns':str(capture_ns)})

    @api.get('/api/latency')
    def latency():
        return monitor.latency_report()

    @api.post('/api/preview/drawn')
    async def preview_drawn(request: Request):
        if request.headers.get('X-Demo-Request') != '1':
            raise HTTPException(403)
        try:
            data = await request.json()
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, '无效的绘制上报') from exc
        samples = data.get('samples') if isinstance(data, dict) else None
        dropped = data.get('dropped', 0)
        if type(dropped) is not int or not 0 <= dropped <= 120:
            raise HTTPException(400, '过期绘制数量无效')
        if not isinstance(samples, list) or len(samples) > 120 or (not samples and not dropped):
            raise HTTPException(400, '绘制上报数量无效')
        accepted = monitor.record_draws(samples, dropped)
        return {'accepted':accepted, 'summary':monitor.latency_summary()}

    @api.post('/api/control/quit')
    def quit_receiver(request: Request):
        if request.headers.get('X-Demo-Request') != '1':
            raise HTTPException(403)
        monitor.exit_requested.set()
        return {'state':'exiting'}

    if not mount_ui:
        return api
    import gradio as gr
    from .ui_parts import header_html, monitor_html
    with gr.Blocks(title='视频解码端', theme=gr.themes.Soft(primary_hue='emerald'),
                   css=(ROOT/'demo/style.css').read_text(), js=(ROOT/'demo/preview.js').read_text()) as ui:
        gr.HTML(header_html('解码端 · 第二台 Jetson'))
        with gr.Column(elem_id='decoder-console'):
            gr.HTML('<div class="session-bar"><div id="live-status" role="status">等待编码端连接</div><span class="session-role">DECODER / DISPLAY</span></div>'
                    '<div class="session-path" id="session-path">在第一台点击开始后，这里会显示链路与画面参数</div>')
            with gr.Row(elem_id='decoder-workspace'):
                with gr.Column(scale=2, min_width=360):
                    gr.HTML(monitor_html('decoded', 'DCVC 重建画面', '第二台 Jetson · HT-S 解码输出', '01'))
                with gr.Column(scale=1, min_width=280):
                    gr.HTML('<div id="live-metrics"></div>')
            gr.HTML('<div class="section-heading compare-heading"><h2>同源硬件对照</h2>'
                    '<span>同一摄像头输入 · NVENC → NVDEC</span></div>'
                    '<div id="hardware-comparison">'
                    + monitor_html('h264', 'H.264 硬件解码', 'NVENC / NVDEC · 独立 ASIC', '02')
                    + monitor_html('h265', 'H.265 硬件解码', 'NVENC / NVDEC · 独立 ASIC', '03')
                    + '</div>')
            gr.Markdown('**处理速度** = 帧数 ÷ 编解码方法累计耗时，含颜色转换和设备拷贝；不含组帧等待、网络、JPEG 展示。**采集→canvas** 由本机浏览器绘制完成后回报，仅在本机打开本页有效；不是物理屏幕光电测量。最近 2 秒更新，初始包含预热。', elem_classes=['metric-note'])
            with gr.Row(elem_classes=['utility-actions']):
                export = gr.Button('保存本次统计')
                quit_button = gr.Button('退出接收程序')
            report = gr.File(label='解码端统计（不含视频）', interactive=False, visible=False)
            export.click(lambda: gr.update(value=monitor.export(), visible=True), outputs=report)
            quit_button.click(lambda: monitor.exit_requested.set())
            with gr.Accordion('详细指标与计时范围', open=False):
                detail = gr.JSON()
                gr.Timer(1).tick(monitor.snapshot, outputs=detail, show_progress='hidden')
        gr.HTML('<div class="app-footer"><span>在编码端点击开始 / 暂停 / 结束 · 不自动录制</span></div>')
    return gr.mount_gradio_app(api, ui, path='/', show_error=True)
