from collections import deque
from dataclasses import asdict
import json
from pathlib import Path
import socket
import threading
import time

from .config import Settings
from .metrics import WindowStats
from .transport import send_packet, recv_packet, ethernet_route, decode_preview


class LatestFrames:
    def __init__(self, limit=8):
        self.items = deque(maxlen=limit)
        self.changed = threading.Condition()
        self.dropped = 0

    def put(self, frame):
        with self.changed:
            if len(self.items) == self.items.maxlen:
                self.dropped += 1
            self.items.append(frame)
            self.changed.notify_all()

    def take(self, count, stop):
        with self.changed:
            while len(self.items) < count and not stop.is_set():
                self.changed.wait(.05)
            if stop.is_set():
                return []
            return [self.items.popleft() for _ in range(count)]


def synthetic_frame(width, height, index):
    import numpy as np
    import cv2
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :, 0] = np.arange(width, dtype=np.uint16)[None, :] % 256
    frame[:, :, 1] = np.arange(height, dtype=np.uint16)[:, None] % 256
    cv2.rectangle(frame, ((index * 6) % width, height // 3),
                  (min((index * 6) % width + 80, width - 1), height // 3 + 70), (255, 220, 70), -1)
    cv2.putText(frame, f'TEST {index:06d}', (16, 38), cv2.FONT_HERSHEY_SIMPLEX, .8, (255, 255, 255), 2)
    return frame


def letterbox(rgb, width, height):
    import cv2
    import numpy as np
    h, w = rgb.shape[:2]
    scale = min(width / w, height / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    resized = cv2.resize(rgb, (nw, nh))
    result = np.zeros((height, width, 3), dtype=np.uint8)
    y, x = (height - nh) // 2, (width - nw) // 2
    result[y:y+nh, x:x+nw] = resized
    return result


class Engine:
    def __init__(self, codec_factory=None):
        if codec_factory is None:
            from .codec import Codec
            codec_factory = Codec
        self.codec_factory = codec_factory
        self.lock = threading.RLock()
        self.control = threading.RLock()
        self.worker = None
        self.capture_thread = None
        self.cancel = threading.Event()
        self.state = 'idle'
        self.message = '就绪：尚未开始采集'
        self.settings = Settings()
        self.original = self.decoded = None
        self.original_seq = self.decoded_seq = 0
        self.queue = LatestFrames()
        self.rates = {key: WindowStats() for key in ('capture', 'encode', 'decode', 'preview')}
        self.timing = {}
        self.sock = None
        self.preview_dropped = 0

    def alive(self):
        return ((self.worker is not None and self.worker.is_alive()) or
                (self.capture_thread is not None and self.capture_thread.is_alive()))

    def start(self, settings):
        settings.validate()
        with self.control:
            self._halt('idle')
            if self.alive():
                raise RuntimeError('上一次任务仍在释放资源，请稍后重试')
            with self.lock:
                self.settings = settings
                self.cancel = threading.Event()
                self.state, self.message = 'starting', '正在初始化；首次模型加载可能较慢'
                self.queue = LatestFrames()
                self.rates = {key: WindowStats() for key in self.rates}
                self.timing = {}
                self.preview_dropped = 0
                self.original = self.decoded = None
                self.worker = threading.Thread(target=self._run, args=(settings, self.cancel), daemon=True)
                self.worker.start()

    def _halt(self, state):
        self.cancel.set()
        sock = self.sock
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        worker = self.worker
        if worker and worker is not threading.current_thread():
            worker.join(timeout=.5)
        with self.lock:
            self.state = state
            self.message = '已暂停；继续将从当前画面重新开始' if state == 'paused' else '已结束，资源释放后可再次开始'

    def stop(self):
        with self.control:
            self._halt('idle')

    def pause(self):
        with self.control:
            if self.state not in ('running', 'starting'):
                raise ValueError('当前没有可以暂停的任务')
            self._halt('paused')

    def snapshot(self):
        with self.lock:
            return {'state': self.state, 'message': self.message, 'settings': asdict(self.settings),
                    **{key: value.snapshot() for key, value in self.rates.items()},
                    'dropped': self.queue.dropped, 'preview_dropped': self.preview_dropped,
                    'timing': dict(self.timing), 'worker_alive': self.alive()}

    def image(self, kind):
        with self.lock:
            if kind == 'original':
                return self.original_seq, self.original
            return self.decoded_seq, self.decoded

    def export(self):
        root = Path(__file__).resolve().parents[1] / 'runs'
        root.mkdir(exist_ok=True)
        path = root / f'report-{time.time_ns()}.json'
        path.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2))
        return str(path)

    def _capture(self, settings, stop, queue, errors):
        import cv2
        cap = None
        try:
            if settings.source == 'camera':
                cap = cv2.VideoCapture(settings.camera, cv2.CAP_V4L2)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.height)
                cap.set(cv2.CAP_PROP_FPS, settings.fps)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if not cap.isOpened():
                    raise RuntimeError(f'无法打开 {settings.camera}，请插入 USB 摄像头后重新检测')
            index, deadline = 0, time.monotonic()
            while not stop.is_set():
                if cap is None:
                    rgb = synthetic_frame(settings.width, settings.height, index)
                else:
                    ok, frame = cap.read()
                    if not ok:
                        raise RuntimeError('摄像头读取失败，可能已拔出')
                    rgb = letterbox(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), settings.width, settings.height)
                captured = time.monotonic()
                if stop.is_set():
                    break
                self.rates['capture'].add(frames=1)
                with self.lock:
                    self.original, self.original_seq = rgb, self.original_seq + 1
                if settings.mode != 'capture':
                    queue.put((captured, rgb))
                index += 1
                deadline += 1 / settings.fps
                if deadline < captured:
                    deadline = captured
                stop.wait(max(0, deadline - time.monotonic()))
        except Exception as exc:
            errors.append(exc)
            stop.set()
        finally:
            if cap is not None:
                cap.release()

    def _run(self, settings, stop):
        cap_thread = None
        play_thread = None
        playback = LatestFrames(limit=16)
        sock = None
        errors = []
        try:
            encoder = decoder = None
            if settings.mode != 'capture':
                encoder = self.codec_factory()
                if stop.is_set():
                    return
                if settings.mode == 'local':
                    decoder = self.codec_factory()
                else:
                    ethernet_route(settings.bind, settings.peer)
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.sock = sock
                    sock.settimeout(10)
                    sock.bind((settings.bind, 0))
                    sock.connect((settings.peer, settings.port))
                    sock.settimeout(120)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if stop.is_set():
                return
            with self.lock:
                if stop.is_set():
                    return
                self.state, self.message = 'running', '采集检查中（不执行压缩）' if settings.mode == 'capture' else 'HT-S 真实码流运行中'
            cap_thread = threading.Thread(target=self._capture, args=(settings, stop, self.queue, errors), daemon=True)
            self.capture_thread = cap_thread
            cap_thread.start()
            if settings.mode != 'capture':
                play_thread = threading.Thread(target=self._play, args=(playback, settings.fps, stop), daemon=True)
                play_thread.start()
            first = True
            while not stop.is_set():
                if settings.mode == 'capture':
                    stop.wait(.05)
                    continue
                batch = self.queue.take(1 if first else 8, stop)
                if not batch:
                    break
                start = time.monotonic()
                packet = encoder.encode([item[1] for item in batch], settings.qp)
                encoded_at = time.monotonic()
                self.rates['encode'].add(frames=len(batch), size=len(packet[1]))
                if stop.is_set():
                    break
                if decoder:
                    output = decoder.decode(packet)
                    decode_ms = (time.monotonic() - encoded_at) * 1000
                else:
                    send_packet(sock, packet[0], packet[1])
                    meta, jpeg_bytes = recv_packet(sock)
                    output, decode_ms = decode_preview(meta, jpeg_bytes, len(batch), settings.width, settings.height)
                self.rates['decode'].add(frames=len(output))
                with self.lock:
                    self.timing = {'encode_group_ms': (encoded_at - start) * 1000,
                                   'decode_group_ms': decode_ms,
                                   'oldest_to_host_ms': (time.monotonic() - batch[0][0]) * 1000,
                                   'scope': '本机采集至本机解码完成' if decoder else '编码端采集至返回解码预览（往返，非单向）'}
                for frame in output:
                    playback.put(frame)
                self.preview_dropped = playback.dropped
                first = False
            if errors:
                raise errors[0]
        except Exception as exc:
            with self.lock:
                # A user-requested cancellation is not a transport failure.
                if not stop.is_set() or errors:
                    self.state, self.message = 'error', f'{type(exc).__name__}: {exc}'
        finally:
            stop.set()
            if cap_thread:
                cap_thread.join(timeout=2)
            if play_thread:
                play_thread.join(timeout=1)
            if sock:
                sock.close()
            self.sock = None

    def _play(self, playback, fps, stop):
        deadline = time.monotonic()
        while not stop.is_set():
            frames = playback.take(1, stop)
            if not frames:
                return
            with self.lock:
                self.decoded, self.decoded_seq = frames[0], self.decoded_seq + 1
            self.rates['preview'].add(frames=1)
            deadline = max(deadline, time.monotonic()) + 1 / fps
            stop.wait(max(0, deadline - time.monotonic()))
