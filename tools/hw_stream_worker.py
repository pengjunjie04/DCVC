"""Low-latency Jetson H.264/H.265 comparison worker.

This process runs under the system Python because GStreamer's Python bindings
are not installed in the project's Miniforge environment. The project process
feeds RGB frames over stdin and reads JSON statistics over stdout.
"""
import argparse
import collections
import json
import math
import os
from pathlib import Path
import queue
import signal
import socket
import struct
import sys
import threading
import time

import gi

gi.require_version('Gst', '1.0')
from gi.repository import Gst


INPUT_HEADER = struct.Struct('!4sQQIII')
OUTPUT_HEADER = struct.Struct('!4sII')
FRAME_HEADER = struct.Struct('!4sqqI')
MAX_ENCODED = 2 * 1024 * 1024
FRAME_DIR = Path('/dev/shm')


def now_ns():
    return time.time_ns()


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        block = stream.read(size - len(data))
        if not block:
            return None
        data.extend(block)
    return bytes(data)


def recv_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        block = sock.recv(size - len(data))
        if not block:
            raise EOFError('peer closed')
        data.extend(block)
    return bytes(data)


def send_packet(sock, metadata, payload):
    meta = json.dumps(metadata, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if not 0 < len(meta) <= 16384 or len(payload) > MAX_ENCODED:
        raise ValueError('invalid hardware stream packet')
    sock.sendall(OUTPUT_HEADER.pack(b'HWV1', len(meta), len(payload)) + meta + payload)


def recv_packet(sock):
    magic, meta_size, size = OUTPUT_HEADER.unpack(recv_exact(sock, OUTPUT_HEADER.size))
    if magic != b'HWV1' or not 0 < meta_size <= 16384 or size > MAX_ENCODED:
        raise ValueError('invalid hardware stream header')
    try:
        metadata = json.loads(recv_exact(sock, meta_size))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('invalid hardware stream metadata') from exc
    if not isinstance(metadata, dict):
        raise ValueError('hardware stream metadata must be an object')
    return metadata, recv_exact(sock, size)


def frame_path(codec):
    return FRAME_DIR / f'dcvc-hw-{codec}.frame'


def write_frame(codec, sequence, capture_ns, jpeg):
    if not jpeg or len(jpeg) > MAX_ENCODED:
        return
    final = frame_path(codec)
    temporary = FRAME_DIR / f'.dcvc-hw-{codec}-{os.getpid()}.tmp'
    temporary.write_bytes(FRAME_HEADER.pack(b'HWF1', sequence, capture_ns, len(jpeg)) + jpeg)
    os.replace(temporary, final)


def read_frame(codec):
    path = frame_path(codec)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    if len(data) < FRAME_HEADER.size:
        return None
    magic, sequence, capture_ns, size = FRAME_HEADER.unpack_from(data)
    if magic != b'HWF1' or not 0 < size <= MAX_ENCODED or len(data) != FRAME_HEADER.size + size:
        return None
    return sequence, capture_ns, data[FRAME_HEADER.size:]


class RateWindow:
    def __init__(self, seconds=2.0):
        self.seconds = seconds
        self.events = collections.deque()
        self.lock = threading.Lock()

    def add(self, size=0, elapsed_ms=None):
        with self.lock:
            self.events.append((time.monotonic(), size, elapsed_ms))

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            while self.events and self.events[0][0] <= now - self.seconds:
                self.events.popleft()
            events = list(self.events)
        elapsed = max(min(now - events[0][0], self.seconds) if events else 0., 1e-6)
        frames = len(events)
        total_ms = sum(item[2] for item in events if item[2] is not None)
        timed_frames = sum(1 for item in events if item[2] is not None)
        latency_ms = events[-1][2] if events and events[-1][2] is not None else None
        return {'fps':frames / elapsed if events else 0.,
                'kbps':sum(item[1] for item in events) * 8 / elapsed / 1000 if events else 0.,
                'compute_fps':timed_frames * 1000 / total_ms if total_ms else 0.,
                'group_ms':latency_ms, 'latency_ms':latency_ms}


class StatsReporter:
    def __init__(self, role):
        self.role = role
        self.lock = threading.Lock()
        self.stats = {}
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def update(self, name, **values):
        with self.lock:
            self.stats[name] = values

    def _run(self):
        while not self.stopped.wait(.5):
            with self.lock:
                values = {codec:dict(item) for codec, item in self.stats.items()}
            print(json.dumps({'type':'stats', 'role':self.role, 'codecs':values},
                             ensure_ascii=False), flush=True)

    def close(self):
        self.stopped.set()


class EncoderStream:
    def __init__(self, codec, peer, port, width, height, fps, bitrate_kbps):
        self.codec = codec
        self.peer = peer
        self.port = port
        self.width = width
        self.height = height
        self.fps = fps
        self.bitrate_kbps = bitrate_kbps
        self.rate = RateWindow()
        self.pending = collections.OrderedDict()
        self.pending_lock = threading.Lock()
        self.send_queue = queue.Queue(maxsize=8)
        self.stop = threading.Event()
        self.sock = None
        self.pipeline = self._build_pipeline()
        self.sender = threading.Thread(target=self._send_loop, daemon=True)
        self.sender.start()

    def _encoder_name(self):
        return 'nvv4l2h264enc' if self.codec == 'h264' else 'nvv4l2h265enc'

    def _parser_name(self):
        return 'h264parse' if self.codec == 'h264' else 'h265parse'

    def _build_pipeline(self):
        caps = (f'video/x-raw,format=RGB,width={self.width},height={self.height},'
                f'framerate={self.fps}/1')
        parser = self._parser_name()
        encoder = self._encoder_name()
        description = (
            f'appsrc name=src is-live=true format=time do-timestamp=false block=false '
            f'max-bytes={max(self.width * self.height * 4 * 2, 1)} caps="{caps}" ! '
            f'videoconvert ! video/x-raw,format=BGRx ! nvvidconv ! '
            f'video/x-raw(memory:NVMM),format=I420 ! {encoder} name=encoder '
            f'bitrate={self.bitrate_kbps * 1000} preset-level=1 iframeinterval={self.fps} '
            f'control-rate=1 insert-sps-pps=1 copy-timestamp=true ! {parser} '
            f'config-interval=-1 ! appsink name=sink emit-signals=true sync=false '
            f'max-buffers=2 drop=true')
        pipeline = Gst.parse_launch(description)
        sink = pipeline.get_by_name('sink')
        sink.connect('new-sample', self._on_sample)
        pipeline.set_state(Gst.State.PLAYING)
        return pipeline

    def _on_sample(self, sink):
        sample = sink.emit('pull-sample')
        if sample is None:
            return Gst.FlowReturn.OK
        buffer = sample.get_buffer()
        pts = buffer.pts
        with self.pending_lock:
            if pts in self.pending:
                sequence, capture_ns, remote_capture_ns = self.pending.pop(pts)
            elif self.pending:
                sequence, capture_ns, remote_capture_ns = self.pending.popitem(last=False)[1]
            else:
                return Gst.FlowReturn.OK
        ok, mapping = buffer.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            payload = bytes(mapping.data)
        finally:
            buffer.unmap(mapping)
        encoded_ns = now_ns()
        encoded_ms = max(0., (encoded_ns - capture_ns) / 1e6)
        self.rate.add(len(payload), encoded_ms)
        packet = ({'codec':self.codec, 'sequence':sequence, 'capture_ns':remote_capture_ns,
                   'fps':self.fps,
                   'encoded_ns':encoded_ns, 'encode_ms':encoded_ms,
                   'width':self.width, 'height':self.height},
                  payload)
        try:
            self.send_queue.put_nowait(packet)
        except queue.Full:
            try:
                self.send_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.send_queue.put_nowait(packet)
            except queue.Full:
                pass
        return Gst.FlowReturn.OK

    def _connect(self):
        while not self.stop.is_set():
            try:
                sock = socket.create_connection((self.peer, self.port), timeout=1)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.sock = sock
                return True
            except OSError:
                if self.stop.wait(.25):
                    return False
        return False

    def _send_loop(self):
        while not self.stop.is_set():
            if self.sock is None and not self._connect():
                return
            try:
                metadata, payload = self.send_queue.get(timeout=.25)
            except queue.Empty:
                continue
            try:
                send_packet(self.sock, metadata, payload)
            except OSError:
                try:
                    self.sock.close()
                except OSError:
                    pass
                self.sock = None

    def push(self, frame, capture_ns, remote_capture_ns, sequence):
        src = self.pipeline.get_by_name('src')
        if src is None:
            return
        pts = int(sequence * 1_000_000_000 / max(self.fps, 1))
        with self.pending_lock:
            self.pending[pts] = (sequence, capture_ns, remote_capture_ns)
            while len(self.pending) > 64:
                self.pending.popitem(last=False)
        buffer = Gst.Buffer.new_wrapped(frame)
        buffer.pts = pts
        buffer.dts = pts
        src.emit('push-buffer', buffer)

    def snapshot(self):
        values = self.rate.snapshot()
        values.update({'connected':self.sock is not None, 'codec':self.codec,
                       'target_kbps':self.bitrate_kbps})
        return values

    def close(self):
        self.stop.set()
        self.pipeline.set_state(Gst.State.NULL)
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sender.join(timeout=1)


class DecoderStream:
    def __init__(self, codec, bind, port, reporter):
        self.codec = codec
        self.bind = bind
        self.port = port
        self.reporter = reporter
        self.net_rate = RateWindow()
        self.decode_rate = RateWindow()
        self.pending = collections.OrderedDict()
        self.pending_lock = threading.Lock()
        self.stop = threading.Event()
        self.pipeline = None
        self.appsrc = None
        self.connected = False
        self.server = None
        self.thread = threading.Thread(target=self._listen, daemon=True)
        self.thread.start()

    def _parser_name(self):
        return 'h264parse' if self.codec == 'h264' else 'h265parse'

    def _build_pipeline(self):
        parser = self._parser_name()
        description = (
            f'appsrc name=src is-live=true format=time do-timestamp=false block=false '
            f'max-bytes={MAX_ENCODED * 2} caps="video/x-{self.codec},stream-format=byte-stream,alignment=au" ! '
            f'{parser} ! nvv4l2decoder enable-max-performance=true disable-dpb=true ! nvvidconv ! '
            f'video/x-raw,format=BGRx ! jpegenc quality=80 ! '
            f'appsink name=sink emit-signals=true sync=false max-buffers=1 drop=true')
        pipeline = Gst.parse_launch(description)
        pipeline.get_by_name('sink').connect('new-sample', self._on_sample)
        pipeline.set_state(Gst.State.PLAYING)
        return pipeline

    def _on_sample(self, sink):
        sample = sink.emit('pull-sample')
        if sample is None:
            return Gst.FlowReturn.OK
        buffer = sample.get_buffer()
        pts = buffer.pts
        with self.pending_lock:
            if pts in self.pending:
                sequence, capture_ns, received_ns = self.pending.pop(pts)
            elif self.pending:
                sequence, capture_ns, received_ns = self.pending.popitem(last=False)[1]
            else:
                return Gst.FlowReturn.OK
        ok, mapping = buffer.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            jpeg = bytes(mapping.data)
        finally:
            buffer.unmap(mapping)
        decoded_ns = now_ns()
        write_frame(self.codec, sequence, capture_ns, jpeg)
        self.decode_rate.add(0, (decoded_ns - capture_ns) / 1e6)
        return Gst.FlowReturn.OK

    def _listen(self):
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.bind, self.port))
            server.listen(1)
            server.settimeout(.5)
            self.server = server
            while not self.stop.is_set():
                try:
                    conn, peer = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    return
                self._receive(conn, peer)

    def _receive(self, conn, peer):
        self.pipeline = self._build_pipeline()
        self.appsrc = self.pipeline.get_by_name('src')
        self.connected = True
        self.pending.clear()
        print(json.dumps({'type':'event', 'codec':self.codec,
                          'message':f'{self.codec.upper()} 已连接 {peer[0]}:{peer[1]}'},
                         ensure_ascii=False), flush=True)
        with conn:
            conn.settimeout(120)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                while not self.stop.is_set():
                    metadata, payload = recv_packet(conn)
                    if metadata.get('codec') != self.codec:
                        raise ValueError('codec mismatch')
                    sequence = metadata.get('sequence')
                    capture_ns = metadata.get('capture_ns')
                    fps = metadata.get('fps', 30)
                    if (type(sequence) is not int or sequence < 0 or type(capture_ns) is not int or
                            capture_ns <= 0 or type(fps) is not int or not 1 <= fps <= 120):
                        raise ValueError('invalid frame metadata')
                    received_ns = now_ns()
                    pts = int(sequence * 1_000_000_000 / fps)
                    with self.pending_lock:
                        self.pending[pts] = (sequence, capture_ns, received_ns)
                        while len(self.pending) > 64:
                            self.pending.popitem(last=False)
                    buffer = Gst.Buffer.new_wrapped(payload)
                    buffer.pts = pts
                    buffer.dts = pts
                    self.appsrc.emit('push-buffer', buffer)
                    self.net_rate.add(len(payload))
            except (EOFError, ConnectionResetError, BrokenPipeError):
                pass
            except Exception as exc:
                print(json.dumps({'type':'event', 'codec':self.codec,
                                  'message':f'{self.codec.upper()} 会话结束：{type(exc).__name__}: {exc}'},
                                 ensure_ascii=False), flush=True)
        self.connected = False
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
        self.pipeline = None
        self.appsrc = None

    def snapshot(self):
        values = self.net_rate.snapshot()
        decoded = self.decode_rate.snapshot()
        values.update({'fps':decoded['fps'], 'compute_fps':decoded['compute_fps'],
                       'group_ms':decoded['group_ms'], 'latency_ms':decoded['latency_ms']})
        values.update({'connected':self.connected, 'codec':self.codec,
                       'target_kbps':None})
        return values

    def close(self):
        self.stop.set()
        try:
            if self.server is not None:
                self.server.close()
        except OSError:
            pass
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
        self.thread.join(timeout=1)


def run_encoder(args):
    reporter = StatsReporter('encoder')
    reporter.start()
    streams = {}
    for codec, port in (('h264', args.h264_port), ('h265', args.h265_port)):
        streams[codec] = EncoderStream(codec, args.peer, port, args.width, args.height,
                                       args.fps, args.bitrate_kbps)
    sequence = 0
    try:
        while True:
            header = read_exact(sys.stdin.buffer, INPUT_HEADER.size)
            if header is None:
                break
            magic, capture_ns, remote_capture_ns, width, height, size = INPUT_HEADER.unpack(header)
            if magic != b'HWF1' or width != args.width or height != args.height or not 0 < size <= width * height * 4:
                raise ValueError('invalid input frame')
            if capture_ns <= 0 or remote_capture_ns <= 0:
                raise ValueError('invalid capture time')
            payload = read_exact(sys.stdin.buffer, size)
            if payload is None:
                break
            for stream in streams.values():
                stream.push(payload, capture_ns, remote_capture_ns, sequence)
            sequence += 1
            if sequence % 10 == 0:
                for codec, stream in streams.items():
                    reporter.update(codec, **stream.snapshot())
    finally:
        for stream in streams.values():
            stream.close()
        reporter.close()


def run_decoder(args):
    reporter = StatsReporter('decoder')
    reporter.start()
    streams = {}
    for codec, port in (('h264', args.h264_port), ('h265', args.h265_port)):
        streams[codec] = DecoderStream(codec, args.bind, port, reporter)
    print(json.dumps({'type':'event', 'message':f'H.264/H.265 接收端口 {args.bind}:{args.h264_port}/{args.h265_port}'},
                     ensure_ascii=False), flush=True)
    try:
        while True:
            time.sleep(.2)
            for codec, stream in streams.items():
                reporter.update(codec, **stream.snapshot())
    finally:
        for stream in streams.values():
            stream.close()
        reporter.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=('encoder', 'decoder'))
    parser.add_argument('--peer', default='192.168.50.2')
    parser.add_argument('--bind', default='192.168.50.2')
    parser.add_argument('--h264-port', type=int, default=9861)
    parser.add_argument('--h265-port', type=int, default=9862)
    parser.add_argument('--width', type=int, default=640)
    parser.add_argument('--height', type=int, default=360)
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--bitrate-kbps', type=int, default=250)
    args = parser.parse_args()
    Gst.init(None)

    def terminate(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        if args.role == 'encoder':
            run_encoder(args)
        else:
            run_decoder(args)
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
