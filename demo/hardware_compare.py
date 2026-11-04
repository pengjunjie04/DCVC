"""Parent-side orchestration for the Jetson hardware codec comparison."""
from collections import deque
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import threading
import time


INPUT_HEADER = struct.Struct('!4sQQIII')
FRAME_HEADER = struct.Struct('!4sqqI')
MAX_FRAME = 2 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / 'tools' / 'hw_stream_worker.py'
SYSTEM_PYTHON = os.environ.get('DCVC_SYSTEM_PYTHON', '/usr/bin/python3')
FRAME_DIR = Path('/dev/shm')


def empty_codec_stats():
    return {'fps':0., 'kbps':0., 'compute_fps':0., 'group_ms':None,
            'latency_ms':None, 'connected':False, 'codec':None,
            'target_kbps':None, 'available':False}


def read_frame(codec):
    path = FRAME_DIR / f'dcvc-hw-{codec}.frame'
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    if len(data) < FRAME_HEADER.size:
        return None
    magic, sequence, capture_ns, size = FRAME_HEADER.unpack_from(data)
    if magic != b'HWF1' or not 0 < size <= MAX_FRAME or len(data) != FRAME_HEADER.size + size:
        return None
    return sequence, capture_ns, data[FRAME_HEADER.size:]


class WorkerStats:
    def __init__(self):
        self.lock = threading.Lock()
        self.stats = {'h264':empty_codec_stats(), 'h265':empty_codec_stats()}
        self.messages = deque(maxlen=20)
        self.error = None

    def update(self, data):
        if data.get('type') == 'event':
            with self.lock:
                self.messages.append(str(data.get('message', ''))[:300])
            return
        if data.get('type') != 'stats' or not isinstance(data.get('codecs'), dict):
            return
        with self.lock:
            for codec in ('h264', 'h265'):
                values = data['codecs'].get(codec)
                if isinstance(values, dict):
                    self.stats[codec] = {**empty_codec_stats(), **values, 'available':True}

    def snapshot(self):
        with self.lock:
            return {'h264':dict(self.stats['h264']), 'h265':dict(self.stats['h265']),
                    'messages':list(self.messages), 'error':self.error}


class WorkerProcess:
    def __init__(self, role, log_path):
        self.role = role
        self.log_path = Path(log_path)
        self.stats = WorkerStats()
        self.process = None
        self.log = None
        self.reader = None
        self.writer = None
        self.stop_event = threading.Event()
        self.write_queue = queue.Queue(maxsize=3)

    def _args(self):
        raise NotImplementedError

    def start(self):
        if self.process is not None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = self.log_path.open('ab', buffering=0)
        command = [SYSTEM_PYTHON, str(WORKER), *self._args()]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.log, bufsize=0)
        self.reader = threading.Thread(target=self._read_output, daemon=True)
        self.reader.start()
        if self.process.stdin is not None:
            self.writer = threading.Thread(target=self._write_input, daemon=True)
            self.writer.start()

    def _read_output(self):
        stream = self.process.stdout
        if stream is None:
            return
        for line in stream:
            try:
                data = json.loads(line.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                self.stats.update(data)

    def _write_input(self):
        stream = self.process.stdin
        if stream is None:
            return
        while not self.stop_event.is_set():
            try:
                item = self.write_queue.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                stream.write(item)
                stream.flush()
            except (BrokenPipeError, OSError) as exc:
                with self.stats.lock:
                    self.stats.error = f'{type(exc).__name__}: {exc}'
                return

    def snapshot(self):
        values = self.stats.snapshot()
        process = self.process
        values['running'] = bool(process is not None and process.poll() is None)
        if process is not None and process.poll() is not None:
            values['exit_code'] = process.returncode
        return values

    def stop(self):
        self.stop_event.set()
        process = self.process
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        if self.reader is not None:
            self.reader.join(timeout=1)
        if self.writer is not None:
            self.writer.join(timeout=1)
        if self.log is not None:
            self.log.close()
        self.process = None


class HardwareEncoder(WorkerProcess):
    def __init__(self, peer, width, height, fps, bitrate_kbps,
                 h264_port=9861, h265_port=9862):
        super().__init__('encoder', '/tmp/dcvc-hw-encoder.log')
        self.peer = peer
        self.width = width
        self.height = height
        self.fps = fps
        self.bitrate_kbps = bitrate_kbps
        self.h264_port = h264_port
        self.h265_port = h265_port

    def _args(self):
        return ['encoder', '--peer', self.peer,
                '--h264-port', str(self.h264_port), '--h265-port', str(self.h265_port),
                '--width', str(self.width), '--height', str(self.height),
                '--fps', str(self.fps), '--bitrate-kbps', str(self.bitrate_kbps)]

    def push(self, frame, capture_ns, remote_capture_ns=None):
        if remote_capture_ns is None:
            remote_capture_ns = capture_ns
        payload = frame.tobytes(order='C')
        header = INPUT_HEADER.pack(b'HWF1', capture_ns, remote_capture_ns,
                                   self.width, self.height, len(payload))
        packet = header + payload
        try:
            self.write_queue.put_nowait(packet)
        except queue.Full:
            try:
                self.write_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.write_queue.put_nowait(packet)
            except queue.Full:
                pass


class HardwareDecoder(WorkerProcess):
    def __init__(self, bind, h264_port=9861, h265_port=9862):
        super().__init__('decoder', '/tmp/dcvc-hw-decoder.log')
        self.bind = bind
        self.h264_port = h264_port
        self.h265_port = h265_port

    def _args(self):
        return ['decoder', '--bind', self.bind,
                '--h264-port', str(self.h264_port), '--h265-port', str(self.h265_port)]

    def frame(self, codec):
        if codec not in ('h264', 'h265'):
            return None
        return read_frame(codec)
