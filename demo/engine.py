from collections import deque
from dataclasses import asdict
import json
from pathlib import Path
from queue import Queue, Empty
import socket
import threading
import time

from .config import Settings
from .metrics import WindowStats, ProcessingStats
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


CAMERA_FORMAT = 'YUYV'


def fourcc_text(value):
    return ''.join(chr((int(value) >> (8 * index)) & 0xff) for index in range(4)).strip('\x00')


def camera_capture_size(settings):
    if settings.width <= 640 and settings.height <= 480:
        return 640, 480
    return settings.width, settings.height


def open_yuyv_camera(settings, cv2):
    width, height = camera_capture_size(settings)
    cap = cv2.VideoCapture(settings.camera, cv2.CAP_V4L2)
    try:
        if not cap.isOpened():
            raise RuntimeError(f'无法打开 {settings.camera}，请插入 USB 摄像头后重新检测')
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*CAMERA_FORMAT))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, settings.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        actual_format = fourcc_text(cap.get(cv2.CAP_PROP_FOURCC))
        actual_width = int(round(cap.get(cv2.CAP_PROP_FRAME_WIDTH)))
        actual_height = int(round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        actual_fps = float(cap.get(cv2.CAP_PROP_FPS))
        if (actual_format != CAMERA_FORMAT or actual_width != width or actual_height != height or
                abs(actual_fps - settings.fps) > .5):
            raise RuntimeError(
                f'摄像头返回 {actual_format or "未知"} {actual_width}x{actual_height}@{actual_fps:.1f}fps；'
                f'需要 YUYV {width}x{height}@{settings.fps}fps，已拒绝 MJPG 或其他隐式回退')
        return cap
    except Exception:
        cap.release()
        raise


class Engine:
    def __init__(self, codec_factory=None, clock_sync=False):
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
        self.processing = {key: ProcessingStats() for key in ('encode', 'decode')}
        self.timing = {}
        self.sock = None
        self.preview_dropped = 0
        self.clock_sync_enabled = clock_sync
        self.clock_offset_ns = 0
        self.clock_sync = {}
        self.hardware = None

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
                self.processing = {key: ProcessingStats() for key in ('encode', 'decode')}
                self.timing = {}
                self.preview_dropped = 0
                self.clock_offset_ns = 0
                self.clock_sync = {}
                self.hardware = None
                self.original = self.decoded = None
                self.worker = threading.Thread(target=self._run, args=(settings, self.cancel), daemon=True)
                self.worker.start()

    def _halt(self, state):
        self.cancel.set()
        hardware = self.hardware
        if hardware is not None:
            hardware.stop()
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
                    'timing': dict(self.timing), 'clock_sync': dict(self.clock_sync),
                    'processing': {key: value.snapshot() for key, value in self.processing.items()},
                    'hardware': self.hardware.snapshot() if self.hardware is not None else None,
                    'worker_alive': self.alive()}

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
                cap = open_yuyv_camera(settings, cv2)
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
                captured_wall_ns = time.time_ns()
                if stop.is_set():
                    break
                self.rates['capture'].add(frames=1)
                with self.lock:
                    self.original, self.original_seq = rgb, self.original_seq + 1
                if settings.mode != 'capture':
                    queue.put((captured, captured_wall_ns, rgb))
                    hardware = self.hardware
                    if hardware is not None:
                        hardware.push(rgb, captured_wall_ns,
                                      captured_wall_ns + self.clock_offset_ns)
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
        response_thread = None
        pending = Queue(maxsize=2)
        slots = threading.BoundedSemaphore(2)
        playback = LatestFrames(limit=16)
        sock = None
        errors = []
        try:
            encoder = decoder = None
            if settings.mode != 'capture':
                if settings.mode == 'send':
                    ethernet_route(settings.bind, settings.peer)
                encoder = self.codec_factory()
                if stop.is_set():
                    return
                if settings.mode == 'local':
                    decoder = self.codec_factory()
                else:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.sock = sock
                    sock.settimeout(10)
                    sock.bind((settings.bind, 0))
                    sock.connect((settings.peer, settings.port))
                    sock.settimeout(120)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    if self.clock_sync_enabled:
                        self._sync_clock(sock)
                    if settings.compare_hardware:
                        from .hardware_compare import HardwareEncoder
                        self.hardware = HardwareEncoder(settings.peer, settings.width, settings.height,
                                                        settings.fps, settings.hardware_kbps)
                        self.hardware.start()
            if stop.is_set():
                return
            with self.lock:
                if stop.is_set():
                    return
                self.state, self.message = 'running', '采集检查中（不执行压缩）' if settings.mode == 'capture' else '视频传输运行中'
            cap_thread = threading.Thread(target=self._capture, args=(settings, stop, self.queue, errors), daemon=True)
            self.capture_thread = cap_thread
            cap_thread.start()
            if settings.mode != 'capture':
                play_thread = threading.Thread(target=self._play, args=(playback, settings.fps, stop), daemon=True)
                play_thread.start()
            if settings.mode == 'send':
                response_thread = threading.Thread(
                    target=self._receive, args=(sock, pending, slots, playback, settings, stop, errors), daemon=True)
                response_thread.start()
            first = True
            while not stop.is_set():
                if settings.mode == 'capture':
                    stop.wait(.05)
                    continue
                if settings.mode == 'send':
                    while not stop.is_set() and not slots.acquire(timeout=.05):
                        pass
                    if stop.is_set():
                        break
                batch = self.queue.take(1 if first else 8, stop)
                if not batch:
                    break
                start = time.monotonic()
                batch_wait_ms = (start - batch[0][0]) * 1000
                batch_span_ms = (batch[-1][0] - batch[0][0]) * 1000
                packet = encoder.encode([item[2] for item in batch], settings.qp)
                encoded_at = time.monotonic()
                self.rates['encode'].add(frames=len(batch), size=len(packet[1]))
                if stop.is_set():
                    break
                encode_ms = (encoded_at - start) * 1000
                self.processing['encode'].add(len(batch), encode_ms)
                if decoder:
                    output = decoder.decode(packet)
                    decode_ms = (time.monotonic() - encoded_at) * 1000
                    self._publish(output, playback, batch[0][0], encode_ms, decode_ms, remote=False)
                else:
                    # FIFO metadata precedes the wire write; one reader owns all replies.
                    pending.put((batch[0][0], batch[-1][0], encode_ms, len(batch),
                                 batch_wait_ms, batch_span_ms))
                    metadata = {**packet[0], 'fps': settings.fps, 'encode_ms': encode_ms,
                                'encode_fps': self.rates['encode'].snapshot()['fps'],
                                'capture_times_ns': [item[1] + self.clock_offset_ns for item in batch]}
                    if self.clock_sync:
                        metadata['clock_sync'] = dict(self.clock_sync)
                    send_packet(sock, metadata, packet[1])
                first = False
            if errors:
                raise errors[0]
        except Exception as exc:
            with self.lock:
                # A user-requested cancellation is not a transport failure.
                if not stop.is_set() or errors:
                    cause = errors[0] if errors else exc
                    self.state, self.message = 'error', f'{type(cause).__name__}: {cause}'
        finally:
            stop.set()
            if sock:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            if response_thread:
                response_thread.join()
            if cap_thread:
                cap_thread.join(timeout=2)
            if play_thread:
                play_thread.join(timeout=1)
            if sock:
                sock.close()
            self.sock = None
            hardware = self.hardware
            self.hardware = None
            if hardware is not None:
                hardware.stop()
            for net in (encoder, decoder):
                close = getattr(net, 'close', None)
                if close is not None:
                    close()
            from .codec import release_workspace
            release_workspace()

    def _sync_clock(self, sock):
        """Estimate decoder_clock - encoder_clock with NTP-style round trips."""
        samples = []
        for index in range(12):
            sent = time.time_ns()
            send_packet(sock, {'type': 'clock_sync', 't0': sent}, b'')
            meta, payload = recv_packet(sock)
            received = time.time_ns()
            if payload or meta.get('type') != 'clock_sync' or meta.get('t0') != sent:
                raise ValueError('解码端时钟校准响应无效')
            remote_received, remote_sent = meta.get('t1'), meta.get('t2')
            if (type(remote_received) is not int or type(remote_sent) is not int or
                    remote_received <= 0 or remote_sent < remote_received):
                raise ValueError('解码端时钟校准时间无效')
            remote_work = remote_sent - remote_received
            round_trip = received - sent - remote_work
            if 0 <= round_trip <= 1_000_000_000:
                offset = ((remote_received - sent) + (remote_sent - received)) // 2
                if index >= 3:
                    samples.append((round_trip, offset))
        if not samples:
            raise RuntimeError('无法测量跨机时钟偏移')
        samples.sort(key=lambda item: item[0])
        best = samples[:min(5, len(samples))]
        offsets = sorted(item[1] for item in best)
        self.clock_offset_ns = offsets[len(offsets) // 2]
        self.clock_sync = {'offset_ms': self.clock_offset_ns / 1e6,
                           'rtt_ms': sorted(item[0] for item in best)[len(best) // 2] / 1e6,
                           'samples': len(best)}
        with self.lock:
            self.clock_sync = dict(self.clock_sync)

    def _receive(self, sock, pending, slots, playback, settings, stop, errors):
        try:
            while not stop.is_set():
                try:
                    captured, newest_captured, encode_ms, count, batch_wait_ms, batch_span_ms = pending.get(timeout=.05)
                except Empty:
                    continue
                meta, jpeg_bytes = recv_packet(sock)
                reply_at = time.monotonic()
                output, decode_ms = decode_preview(meta, jpeg_bytes, count, settings.width, settings.height)
                if stop.is_set():
                    return
                self._publish(output, playback, captured, encode_ms, decode_ms, remote=True,
                              newest_captured=newest_captured, batch_wait_ms=batch_wait_ms,
                              batch_span_ms=batch_span_ms, reply_at=reply_at)
                slots.release()
        except Exception as exc:
            if not stop.is_set():
                errors.append(exc)
                stop.set()
                # A peer rejecting a reply may also stop reading our next group.
                # Interrupt sendall so the worker reports this original error promptly.
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def _publish(self, output, playback, captured, encode_ms, decode_ms, remote,
                 newest_captured=None, batch_wait_ms=None, batch_span_ms=None, reply_at=None):
        self.rates['decode'].add(frames=len(output))
        self.processing['decode'].add(len(output), decode_ms)
        with self.lock:
            now = reply_at or time.monotonic()
            timing = {'encode_group_ms': encode_ms,
                      'decode_group_ms': decode_ms,
                      'oldest_to_host_ms': (now - captured) * 1000,
                      'scope': '编码端采集至返回解码预览（往返，非单向）' if remote else '本机采集至本机解码完成'}
            if newest_captured is not None:
                timing['newest_to_host_ms'] = (now - newest_captured) * 1000
            if batch_wait_ms is not None:
                timing['batch_wait_ms'] = batch_wait_ms
            if batch_span_ms is not None:
                timing['batch_span_ms'] = batch_span_ms
            self.timing = timing
        for frame in output:
            playback.put(frame)
        self.preview_dropped = playback.dropped

    def _play(self, playback, fps, stop):
        deadline = time.monotonic()
        while not stop.is_set():
            frames = playback.take(1, stop)
            if not frames:
                return
            now = time.monotonic()
            if now > deadline + 1 / fps:
                deadline = now
            with self.lock:
                self.decoded, self.decoded_seq = frames[0], self.decoded_seq + 1
            self.rates['preview'].add(frames=1)
            deadline += 1 / fps
            stop.wait(max(0, deadline - time.monotonic()))
