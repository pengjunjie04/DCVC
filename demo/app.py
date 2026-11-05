import argparse
import glob
import threading
import time
import webbrowser
import subprocess
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from .codec import readiness
from .config import Settings
from .engine import Engine
from .ui_parts import header_html, monitor_html

ROOT = Path(__file__).resolve().parents[1]
MODES = {'本机编解码': 'local', '双机发送': 'send', '仅检查采集 · 不压缩': 'capture'}
SOURCES = {'测试图案（无需摄像头）': 'synthetic', 'USB 摄像头': 'camera'}
RESOLUTIONS = {'360p · 640 × 360': (640, 360), '240p · 416 × 240': (416, 240),
               '480p · 832 × 480': (832, 480), '720p · 1280 × 720': (1280, 720),
               '1080p · 1920 × 1080': (1920, 1080)}


def device_status():
    cameras = glob.glob('/dev/video*')
    problems = readiness()
    try:
        network = json.loads(subprocess.check_output(['ip', '-j', '-4', 'addr'], text=True, timeout=3))
        addresses = {row['ifname']: [entry['local'] for entry in row['addr_info']] for row in network if row['ifname'] != 'lo'}
    except (OSError, subprocess.SubprocessError, ValueError):
        addresses = '无法读取，请运行 ip -4 addr 查看'
    return {'摄像头': cameras or ['未插入或尚未识别'], '本机 IPv4': addresses, '模型': problems or ['权重和扩展已就绪'],
            '第二台': '请先启动接收脚本并填写两端有线 IP；点击开始时检测连接',
            '验收目标': '640×360 / 30fps / ≤500ms；完整显示延迟仍需单独测量'}


def device_text():
    status = device_status()
    network = status['本机 IPv4']
    addresses = '；'.join(f'{name}: {", ".join(values)}' for name, values in network.items()) if isinstance(network, dict) else network
    return ('**摄像头**：' + '；'.join(status['摄像头']) + '\n\n**模型**：' + '；'.join(status['模型']) +
            '\n\n**本机地址**：' + (addresses or '暂无') + '\n\n**解码端**：' + status['第二台'])


def create_app(engine=None, mount_ui=True):
    engine = engine or Engine()
    api = FastAPI(title='视频传输控制台')
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

    def operate(action, mode, source, resolution, fps, qp, compare, hardware_kbps,
                camera, bind, peer, port):
        try:
            if action in ('start', 'apply'):
                width, height = RESOLUTIONS[resolution]
                settings = Settings(width=width, height=height, fps=int(fps), qp=int(qp),
                                    mode=MODES[mode], source=SOURCES[source], camera=camera,
                                    bind=bind.strip(), peer=peer.strip(), port=int(port),
                                    compare_hardware=bool(compare), hardware_kbps=int(hardware_kbps))
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
    with gr.Blocks(title='视频传输控制台', theme=gr.themes.Soft(primary_hue='emerald'), css=css, js=js) as ui:
        gr.HTML(header_html())
        with gr.Row(elem_id='workspace'):
            with gr.Column(scale=1, min_width=280, elem_id='settings-panel'):
                gr.HTML('<div class="panel-heading"><span class="eyebrow">CONFIGURATION</span><h2>运行设置</h2><p>视频源、分辨率与本次实验参数</p></div>')
                mode = gr.Dropdown(list(MODES), value=list(MODES)[1], label='运行模式')
                source = gr.Dropdown(list(SOURCES), value=list(SOURCES)[1], label='视频源')
                resolution = gr.Dropdown(list(RESOLUTIONS), value=list(RESOLUTIONS)[0], label='处理分辨率')
                fps = gr.Slider(1, 60, value=30, step=1, label='目标帧率 / fps')
                qp = gr.Slider(0, 63, value=32, step=1, label='量化参数 QP（非目标 kbps）')
                compare = gr.Checkbox(value=True, label='实时 H.264/H.265 对比')
                hardware_kbps = gr.Slider(32, 2000, value=250, step=1,
                                          label='H.264/H.265 目标码率 / kbps')
                with gr.Accordion('设备与有线网络', open=False):
                    camera = gr.Textbox('/dev/video0', label='摄像头节点')
                    bind = gr.Textbox('192.168.50.1', label='本机有线 IPv4', placeholder='例如 192.168.50.1')
                    peer = gr.Textbox('192.168.50.2', label='解码端有线 IPv4', placeholder='例如 192.168.50.2')
                    port = gr.Number(9860, precision=0, label='码流端口')
                gr.Markdown('参数修改后，点击 **应用并重启**。暂停期间不保存或积压画面。')
            with gr.Column(scale=3, elem_id='main-console'):
                gr.HTML('<div class="session-bar"><div id="live-status" role="status">尚未运行</div><span class="session-role">ENCODER / CONTROL</span></div><div class="session-path" id="session-path">设置参数后点击开始，画面与指标将自动更新</div>')
                with gr.Row(elem_classes=['primary-actions']):
                    start = gr.Button('▶ 开始', variant='primary')
                    pause = gr.Button('Ⅱ 暂停')
                    resume = gr.Button('▷ 继续')
                    stop = gr.Button('■ 结束', variant='stop')
                gr.HTML('<div class="previews single">' +
                        monitor_html('original', '采集原始画面', '输入 · USB 摄像头 / 测试图案', '01') + '</div>')
                gr.HTML('<div id="live-metrics"></div><p class="metric-note">吞吐 FPS 含等待；处理速度 = 帧数 ÷ 编解码方法耗时（含转换与拷贝）。kbps 仅含模型载荷。返回预览时延不含浏览器显示。</p>')
                with gr.Row(elem_classes=['utility-actions']):
                    apply = gr.Button('应用并重启')
                    refresh = gr.Button('重新检测设备')
                    export = gr.Button('保存本次统计')
                    quit_button = gr.Button('退出程序')
                with gr.Accordion('设备就绪情况', open=False):
                    device_panel = gr.Markdown(value=device_text())
                with gr.Accordion('详细指标与运行记录', open=False):
                    status = gr.JSON(value=engine.snapshot())
                report = gr.File(label='统计报告（不含视频）', interactive=False, visible=False)
        inputs = [mode, source, resolution, fps, qp, compare, hardware_kbps,
                  camera, bind, peer, port]
        for button, action in [(start, 'start'), (pause, 'pause'), (resume, 'resume'), (stop, 'stop'), (apply, 'apply'), (quit_button, 'quit')]:
            def callback(*args, action=action):
                return operate(action, *args)
            button.click(callback, inputs=inputs, outputs=status, concurrency_limit=1, concurrency_id='controls')
        refresh.click(device_text, outputs=device_panel)
        export.click(lambda: gr.update(value=engine.export(), visible=True), outputs=report)
        timer = gr.Timer(1)
        timer.tick(engine.snapshot, outputs=status, show_progress='hidden')
        gr.HTML('<div class="app-footer"><span>本地运行 · 不自动录制 · 性能以实测为准</span></div>')
    return gr.mount_gradio_app(api, ui, path='/', show_error=True)


def main():
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1', help='默认本机；填写 Wi-Fi IP 可供同网电脑访问')
    parser.add_argument('--port', type=int, default=7860)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    engine = Engine(clock_sync=True)
    app = create_app(engine)
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level='info', access_log=False))
    def watch():
        while not server.started and not server.should_exit:
            time.sleep(.1)
        if not args.no_browser and server.started:
            browser_host = '127.0.0.1' if args.host == '0.0.0.0' else args.host
            webbrowser.open(f'http://{browser_host}:{args.port}')
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
