import argparse
import glob
import json
import subprocess
import threading
import time
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .codec import readiness
from .config import Settings
from .engine import Engine

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'demo' / 'web'


def device_status():
    cameras = glob.glob('/dev/video*')
    problems = readiness()
    try:
        network = json.loads(subprocess.check_output(['ip', '-j', '-4', 'addr'], text=True, timeout=3))
        addresses = {row['ifname']: [entry['local'] for entry in row['addr_info']] for row in network if row['ifname'] != 'lo'}
    except (OSError, subprocess.SubprocessError, ValueError):
        addresses = '无法读取，请运行 ip -4 addr 查看'
    return {'摄像头': cameras or ['未插入或尚未识别'], '本机IPv4': addresses, '模型': problems or ['权重和扩展已就绪'],
            '第二台': '请先启动接收脚本并填写两端有线 IP；点击开始时检测连接',
            '验收目标': '640×360 / 30fps / ≤500ms；完整显示延迟仍需单独测量'}


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

    @api.post('/api/report')
    def report(request: Request):
        if request.headers.get('X-Demo-Request') != '1':
            raise HTTPException(403, '请从本地演示界面操作')
        path = Path(engine.export())
        return FileResponse(path, media_type='application/json', filename=path.name)

    @api.post('/api/control/{action}')
    async def control(action: str, request: Request):
        if request.headers.get('X-Demo-Request') != '1':
            raise HTTPException(403, '请从本地演示界面操作')
        try:
            if action in ('start', 'apply'):
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

    if mount_ui:
        api.mount('/assets', StaticFiles(directory=WEB), name='assets')

        @api.get('/')
        def index():
            return FileResponse(WEB / 'encoder.html', media_type='text/html')

    return api


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
