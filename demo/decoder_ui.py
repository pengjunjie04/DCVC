"""Decoder-local monitor: JPEG-only parent process, no additional CUDA model."""
import json
from pathlib import Path
import threading
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from .engine import LatestFrames
from .metrics import ProcessingStats, WindowStats

ROOT = Path(__file__).resolve().parents[1]


class DecoderMonitor:
    def __init__(self):
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.exit_requested = threading.Event()
        self.queue = LatestFrames(limit=16)
        self.jpeg = None
        self.seq = self.epoch = 0
        self.state, self.message = 'waiting', '等待编码端连接；请在第一台点击开始'
        self.settings = {'mode':'send', 'width':640, 'height':360, 'fps':30, 'qp':32}
        self._reset_rates()
        self.player = threading.Thread(target=self._play, daemon=True)
        self.player.start()

    def _reset_rates(self):
        self.decode = WindowStats()
        self.preview = WindowStats()
        self.processing = {name:ProcessingStats() for name in ('encode', 'decode')}
        self.ipc_dropped = 0
        self.encode_fps = 0.
        self.totals = {'frames':0, 'bytes':0, 'encode_ms':0., 'decode_ms':0.}

    def begin_session(self):
        with self.lock:
            self.epoch += 1
            self._reset_rates()
            self.state, self.message = 'starting', '连接已建立，正在加载解码模型和首组画面'
            with self.queue.changed:
                self.queue.items.clear()
                self.queue.dropped = 0

    def accept(self, info, previews):
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
            for jpeg in previews:
                self.queue.put((self.epoch, jpeg, self.settings['fps']))

    def end_session(self, code):
        with self.lock:
            self.state = 'waiting' if code == 0 else 'error'
            self.message = '会话已结束，保留最后画面；等待编码端再次开始' if code == 0 else f'解码会话退出（{code}），等待下一次连接'
            self.encode_fps = 0.

    def _play(self):
        deadline = time.monotonic()
        while not self.closed.is_set():
            items = self.queue.take(1, self.closed)
            if not items:
                return
            epoch, jpeg, fps = items[0]
            now = time.monotonic()
            if now > deadline + 1 / fps:
                deadline = now
            if self.closed.wait(max(0, deadline - now)):
                return
            with self.lock:
                if epoch != self.epoch:
                    continue
                self.jpeg, self.seq = jpeg, self.seq + 1
                self.preview.add(frames=1)
            deadline += 1 / fps

    def snapshot(self):
        with self.lock:
            decode = self.decode.snapshot()
            return {'role':'decoder', 'state':self.state, 'message':self.message,
                    'settings':dict(self.settings), 'capture':{'fps':0},
                    'encode':{'fps':self.encode_fps if decode['fps'] else 0., 'mbps':decode['mbps']},
                    'decode':decode, 'preview':self.preview.snapshot(),
                    'processing':{key:value.snapshot() for key,value in self.processing.items()},
                    'timing':{}, 'dropped':0, 'preview_dropped':self.queue.dropped + self.ipc_dropped}

    def image(self):
        with self.lock:
            return self.seq, self.jpeg

    def export(self):
        path = ROOT / 'runs' / f'decoder-report-{time.time_ns()}.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2))
        return str(path)

    def close(self):
        self.closed.set()
        self.player.join(timeout=1)


def create_decoder_app(monitor, mount_ui=True):
    api = FastAPI(title='DCVC Lab · Decoder')

    @api.get('/api/state')
    def state():
        return monitor.snapshot()

    @api.get('/api/frame/decoded')
    def frame(after: int = -1):
        seq, jpeg = monitor.image()
        if jpeg is None or seq == after:
            return Response(status_code=204, headers={'Cache-Control':'no-store'})
        return Response(jpeg, media_type='image/jpeg', headers={'X-Sequence':str(seq), 'Cache-Control':'no-store'})

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
    with gr.Blocks(title='DCVC Lab · 解码端', theme=gr.themes.Soft(primary_hue='emerald'),
                   css=(ROOT/'demo/style.css').read_text(), js=(ROOT/'demo/preview.js').read_text()) as ui:
        gr.HTML(header_html('解码端 · 第二台 Jetson'))
        with gr.Column(elem_id='decoder-console'):
            gr.HTML('<div class="session-bar"><div id="live-status" role="status">等待编码端连接</div><span class="session-role">DECODER / DISPLAY</span></div>')
            with gr.Row(elem_id='decoder-workspace'):
                with gr.Column(scale=2, min_width=360):
                    gr.HTML(monitor_html('decoded', '解码输出', '第二台 Jetson · HT-S 重建画面'))
                with gr.Column(scale=1, min_width=280):
                    gr.HTML('<div class="section-heading"><h2>实时性能</h2><span>实时吞吐 / 处理速度</span></div><div class="metric-grid" id="live-metrics"></div>')
            gr.Markdown('**处理速度** = 帧数 ÷ 编解码方法累计耗时，含颜色转换和设备拷贝；不含组帧等待、网络、JPEG 展示。最近 2 秒更新，初始包含预热。与论文对照还需匹配硬件、输入、QP 和计时方法。', elem_classes=['metric-note'])
            with gr.Row(elem_classes=['utility-actions']):
                export = gr.Button('保存本次统计')
                quit_button = gr.Button('退出接收程序')
            report = gr.File(label='解码端统计（不含视频）', interactive=False, visible=False)
            export.click(lambda: gr.update(value=monitor.export(), visible=True), outputs=report)
            quit_button.click(lambda: monitor.exit_requested.set())
            with gr.Accordion('详细指标与计时范围', open=False):
                detail = gr.JSON()
                gr.Timer(1).tick(monitor.snapshot, outputs=detail, show_progress='hidden')
        gr.HTML('<div class="app-footer"><span>DCVC-UF HT-S · 第二台独立解码</span><span>在编码端点击开始 / 暂停 / 结束 · 不自动录制</span></div>')
    return gr.mount_gradio_app(api, ui, path='/', show_error=True)
