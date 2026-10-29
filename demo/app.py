import argparse
import glob
import threading
import time
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from .codec import readiness
from .config import Settings
from .engine import Engine

ROOT = Path(__file__).resolve().parents[1]
MODES = {'本机编解码 · HT-S': 'local', '双机发送 · HT-S': 'send', '仅检查采集 · 不压缩': 'capture'}
SOURCES = {'测试图案（无需摄像头）': 'synthetic', 'USB 摄像头': 'camera'}
RESOLUTIONS = {'360p · 640 × 360': (640, 360), '240p · 416 × 240': (416, 240),
               '480p · 832 × 480': (832, 480), '720p · 1280 × 720': (1280, 720),
               '1080p · 1920 × 1080': (1920, 1080)}


def device_status():
    cameras = glob.glob('/dev/video*')
    problems = readiness()
    return {'摄像头': cameras or ['未插入或尚未识别'], 'HT-S': problems or ['权重和扩展已就绪；实际运行仍需验证'],
            '第二台': '请先启动接收脚本并填写两端有线 IP；点击开始时检测连接',
            '验收目标': '640×360 / 30fps / ≤500ms，尚未完成双机实测'}


def create_app(engine=None, mount_ui=True):
    engine = engine or Engine()
    api = FastAPI(title='Jetson DCVC Lab')
    api.state.engine = engine
    api.state.exit_requested = threading.Event()

    @api.get('/api/state')
    def state():
        return engine.snapshot()

    @api.get('/api/devices')
    def devices():
        return device_status()

    @api.get('/api/frame/{kind}')
    def frame(kind: str, after: int = -1):
        if kind not in ('original', 'decoded'):
            raise HTTPException(404)
        seq, rgb = engine.image(kind)
        if rgb is None or after == seq:
            return Response(status_code=204, headers={'Cache-Control': 'no-store'})
        import cv2
        ok, jpeg = cv2.imencode('.jpg', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            raise HTTPException(500, '预览转换失败')
        return Response(jpeg.tobytes(), media_type='image/jpeg',
                        headers={'X-Sequence': str(seq), 'Cache-Control': 'no-store'})

    @api.post('/api/control/{action}')
    async def control(action: str, request: Request):
        if request.headers.get('X-Demo-Request') != '1':
            raise HTTPException(403, '请从本地演示界面操作')
        try:
            if action == 'start':
                data = await request.json()
                engine.start(Settings(**data))
            elif action == 'pause':
                engine.pause()
            elif action == 'resume':
                engine.start(engine.settings)
            elif action == 'stop':
                engine.stop()
            elif action == 'quit':
                engine.stop()
                api.state.exit_requested.set()
            else:
                raise ValueError('未知操作')
            return engine.snapshot()
        except (TypeError, ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    if not mount_ui:
        return api
    import gradio as gr

    def operate(action, mode, source, resolution, fps, qp, camera, bind, peer, port):
        try:
            if action in ('start', 'apply'):
                width, height = RESOLUTIONS[resolution]
                settings = Settings(width=width, height=height, fps=int(fps), qp=int(qp),
                                    mode=MODES[mode], source=SOURCES[source], camera=camera,
                                    bind=bind.strip(), peer=peer.strip(), port=int(port))
                engine.start(settings)
            elif action == 'pause':
                engine.pause()
            elif action == 'resume':
                engine.start(engine.settings)
            elif action == 'stop':
                engine.stop()
            elif action == 'quit':
                engine.stop()
                api.state.exit_requested.set()
            return engine.snapshot()
        except Exception as exc:
            gr.Warning(str(exc))
            return {**engine.snapshot(), '操作提示': str(exc)}

    css = (ROOT / 'demo' / 'style.css').read_text()
    js = (ROOT / 'demo' / 'preview.js').read_text()
    with gr.Blocks(title='Jetson DCVC Lab', theme=gr.themes.Soft(primary_hue='emerald'), css=css, js=js) as ui:
        gr.HTML('''<div class="masthead"><div><div class="eyebrow">JETSON ORIN NX · NEURAL VIDEO COMPRESSION</div>
        <h1>DCVC <span>Lab</span></h1><p>双机神经视频压缩实验台 · DCVC-UF HT-S</p></div>
        <div class="target">第一阶段目标<b>360p / 30 fps</b><small>延迟目标 ≤ 500 ms · 实测验证中</small></div></div>''')
        with gr.Row():
            with gr.Column(scale=1, min_width=280):
                gr.Markdown('### 运行设置')
                mode = gr.Dropdown(list(MODES), value=list(MODES)[0], label='运行模式')
                source = gr.Dropdown(list(SOURCES), value=list(SOURCES)[0], label='视频源')
                resolution = gr.Dropdown(list(RESOLUTIONS), value=list(RESOLUTIONS)[0], label='处理分辨率')
                fps = gr.Slider(1, 60, value=30, step=1, label='目标帧率 / fps')
                qp = gr.Slider(0, 63, value=32, step=1, label='量化参数 QP（非目标 Mbps）')
                with gr.Accordion('设备与有线网络', open=False):
                    camera = gr.Textbox('/dev/video0', label='摄像头节点')
                    bind = gr.Textbox(label='本机有线 IPv4', placeholder='例如 192.168.50.1')
                    peer = gr.Textbox(label='解码端有线 IPv4', placeholder='例如 192.168.50.2')
                    port = gr.Number(9860, precision=0, label='码流端口')
                gr.Markdown('参数修改后，点击 **应用并重启**。暂停期间不保存或积压画面。')
            with gr.Column(scale=3):
                gr.HTML('''<div class="previews"><section><div class="preview-title">采集原始画面 <span id="fps-original">0.0 fps</span></div>
                <canvas id="preview-original" width="640" height="360" aria-label="原始视频画面"></canvas><p>未开始时不采集；测试图案会显示 TEST 标记。</p></section>
                <section><div class="preview-title">HT-S 解码画面 <span id="fps-decoded">0.0 fps</span></div>
                <canvas id="preview-decoded" width="640" height="360" aria-label="解码视频画面"></canvas><p>右上角为浏览器实际绘制帧率，独立于解码 FPS。</p></section></div>''')
                gr.HTML('''<div id="live-status" role="status">尚未运行</div><div class="metric-grid" id="live-metrics"></div>
                <p class="metric-note">压缩 Mbps 仅统计模型码流载荷；不含协议、原始预览和返回预览开销。延迟范围见下方运行记录。</p>''')
                with gr.Row():
                    start = gr.Button('▶ 开始', variant='primary')
                    pause = gr.Button('Ⅱ 暂停')
                    resume = gr.Button('▷ 继续')
                    stop = gr.Button('■ 结束', variant='stop')
                with gr.Row():
                    apply = gr.Button('应用并重启')
                    refresh = gr.Button('重新检测设备')
                    export = gr.Button('保存本次统计')
                    quit_button = gr.Button('退出程序')
                with gr.Accordion('设备就绪情况', open=True):
                    device_json = gr.JSON(value=device_status())
                with gr.Accordion('详细指标与运行记录', open=False):
                    status = gr.JSON(value=engine.snapshot())
                report = gr.File(label='统计报告（不含视频）', interactive=False)
        inputs = [mode, source, resolution, fps, qp, camera, bind, peer, port]
        for button, action in [(start, 'start'), (pause, 'pause'), (resume, 'resume'), (stop, 'stop'), (apply, 'apply'), (quit_button, 'quit')]:
            def callback(*args, action=action):
                return operate(action, *args)
            button.click(callback, inputs=inputs, outputs=status, concurrency_limit=1, concurrency_id='controls')
        refresh.click(device_status, outputs=device_json)
        export.click(engine.export, outputs=report)
        timer = gr.Timer(1)
        timer.tick(engine.snapshot, outputs=status, show_progress='hidden')
        gr.Markdown('本地研究演示 · 无音频 · 不自动录制 · 第二台与 USB 摄像头待接入验收')
    return gr.mount_gradio_app(api, ui, path='/', show_error=True)


def main():
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=7860)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    engine = Engine()
    app = create_app(engine)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, log_level='info'))
    def watch():
        while not server.started and not server.should_exit:
            time.sleep(.1)
        if not args.no_browser and server.started:
            webbrowser.open(f'http://127.0.0.1:{args.port}')
        while not server.should_exit:
            if app.state.exit_requested.wait(.2):
                server.should_exit = True
    threading.Thread(target=watch, daemon=True).start()
    try:
        server.run()
    finally:
        engine.stop()


if __name__ == '__main__':
    main()
