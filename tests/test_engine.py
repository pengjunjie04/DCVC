import socket
import threading
import time
import unittest

from demo.config import Settings
from demo.engine import Engine, LatestFrames, camera_capture_size, fourcc_text, open_yuyv_camera
from demo.transport import recv_packet, send_packet


class EngineTests(unittest.TestCase):
    def test_camera_uses_uncompressed_640x480_for_360p_output(self):
        settings = Settings(source='camera', width=640, height=360, fps=30)
        self.assertEqual(camera_capture_size(settings), (640, 480))
        self.assertEqual(fourcc_text(0x56595559), 'YUYV')

    def test_camera_requests_yuyv_before_resolution_and_verifies_mode(self):
        fake = FakeCv2()
        cap = open_yuyv_camera(Settings(source='camera', width=640, height=360, fps=30), fake)
        props = [prop for prop, _ in cap.sets]
        self.assertLess(props.index(fake.CAP_PROP_FOURCC), props.index(fake.CAP_PROP_FRAME_WIDTH))
        self.assertEqual(cap.get(fake.CAP_PROP_FRAME_WIDTH), 640)
        self.assertEqual(cap.get(fake.CAP_PROP_FRAME_HEIGHT), 480)
        self.assertEqual(fourcc_text(cap.get(fake.CAP_PROP_FOURCC)), 'YUYV')

    def test_camera_rejects_silent_mjpg_fallback(self):
        fake = FakeCv2(actual_fourcc=fake_fourcc('MJPG'), ignore_fourcc=True)
        with self.assertRaisesRegex(RuntimeError, 'MJPG|YUYV'):
            open_yuyv_camera(Settings(source='camera'), fake)
        self.assertTrue(fake.capture.released)

    def test_camera_rejects_mode_it_could_not_negotiate(self):
        fake = FakeCv2(actual_fps=10., ignore_fps=True)
        with self.assertRaisesRegex(RuntimeError, '30fps|模式'):
            open_yuyv_camera(Settings(source='camera', fps=30), fake)
        self.assertTrue(fake.capture.released)

    def test_playback_preserves_interval_after_input_starvation(self):
        engine = Engine()
        queue = LatestFrames()
        stop = threading.Event()
        thread = threading.Thread(target=engine._play, args=(queue, 30, stop))
        thread.start()
        try:
            queue.put('warmup')
            time.sleep(.2)
            queue.put('a')
            queue.put('b')
            seen = {}
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and len(seen) < 2:
                seq, frame = engine.image('decoded')
                if frame in ('a', 'b') and frame not in seen:
                    seen[frame] = time.monotonic()
                time.sleep(.001)
            self.assertEqual(set(seen), {'a', 'b'})
            self.assertGreater(seen['b'] - seen['a'], .02)
        finally:
            stop.set()
            thread.join(1)

    def test_preview_pacing_does_not_halve_codec_throughput(self):
        class FastCodec:
            first = True
            def encode(self, frames, qp):
                time.sleep(.05)
                self.first = False
                return frames, b'abc'
            def decode(self, packet):
                return packet[0]
        engine = Engine(codec_factory=FastCodec)
        try:
            engine.start(Settings(fps=120))
            time.sleep(2.2)
            self.assertGreaterEqual(engine.snapshot()['encode']['frames'], 150)
        finally:
            engine.stop()

    def test_latest_queue_discards_old_unencoded_frames(self):
        q = LatestFrames(limit=8)
        for i in range(20):
            q.put(i)
        self.assertEqual(q.take(8, threading.Event()), list(range(12, 20)))
        self.assertEqual(q.dropped, 12)

    def test_capture_mode_starts_pauses_resumes_stops(self):
        engine = Engine()
        try:
            engine.start(Settings(mode='capture'))
            deadline = time.monotonic() + 3
            while engine.snapshot()['capture']['frames'] < 3 and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertGreaterEqual(engine.snapshot()['capture']['frames'], 3)
            engine.pause()
            self.assertEqual(engine.snapshot()['state'], 'paused')
            count = engine.snapshot()['capture']['frames']
            time.sleep(.1)
            self.assertEqual(engine.snapshot()['capture']['frames'], count)
            engine.start(Settings(mode='capture'))
            time.sleep(.2)
            engine.stop()
            self.assertEqual(engine.snapshot()['state'], 'idle')
            self.assertFalse(engine.alive())
        finally:
            engine.stop()

    def test_stop_during_model_loading_prevents_late_start(self):
        entered, release = threading.Event(), threading.Event()
        def load():
            entered.set()
            release.wait(3)
            return object()
        engine = Engine(codec_factory=load)
        try:
            engine.start(Settings())
            self.assertTrue(entered.wait(2))
            engine.stop()
            release.set()
            deadline = time.monotonic() + 2
            while engine.alive() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertEqual(engine.snapshot()['state'], 'idle')
            self.assertEqual(engine.snapshot()['capture']['frames'], 0)
            self.assertFalse(engine.alive())
        finally:
            release.set()
            engine.stop()

    def test_model_failure_remains_visible_and_retryable(self):
        def load():
            raise RuntimeError('missing checkpoint')
        engine = Engine(codec_factory=load)
        engine.start(Settings())
        deadline = time.monotonic() + 2
        while engine.alive() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertEqual(engine.snapshot()['state'], 'error')
        self.assertIn('missing checkpoint', engine.snapshot()['message'])
        engine.start(Settings(mode='capture'))
        time.sleep(.1)
        engine.stop()
        self.assertEqual(engine.snapshot()['state'], 'idle')

    def test_clock_sync_estimates_near_zero_offset_on_socket_pair(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        def peer():
            try:
                for _ in range(12):
                    meta, payload = recv_packet(right)
                    received = time.time_ns()
                    self.assertFalse(payload)
                    self.assertEqual(meta['type'], 'clock_sync')
                    send_packet(right, {'type':'clock_sync', 't0':meta['t0'],
                                        't1':received, 't2':time.time_ns()}, b'')
            finally:
                right.close()
        thread = threading.Thread(target=peer)
        thread.start()
        engine = Engine(clock_sync=True)
        engine._sync_clock(left)
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertLess(abs(engine.clock_sync['offset_ms']), 20)
        self.assertLess(engine.clock_sync['rtt_ms'], 50)
        self.assertGreaterEqual(engine.clock_sync['samples'], 5)


def fake_fourcc(value):
    return sum(ord(char) << (8 * index) for index, char in enumerate(value))


class FakeCapture:
    def __init__(self, actual_fourcc, actual_fps, ignore_fourcc=False, ignore_fps=False):
        self.actual_fourcc = actual_fourcc
        self.actual_fps = actual_fps
        self.ignore_fourcc = ignore_fourcc
        self.ignore_fps = ignore_fps
        self.width = 640
        self.height = 480
        self.sets = []
        self.released = False

    def isOpened(self):
        return True

    def set(self, prop, value):
        self.sets.append((prop, value))
        if prop == FakeCv2.CAP_PROP_FOURCC:
            if not self.ignore_fourcc:
                self.actual_fourcc = value
        elif prop == FakeCv2.CAP_PROP_FRAME_WIDTH:
            self.width = value
        elif prop == FakeCv2.CAP_PROP_FRAME_HEIGHT:
            self.height = value
        elif prop == FakeCv2.CAP_PROP_FPS:
            if not self.ignore_fps:
                self.actual_fps = value
        return True

    def get(self, prop):
        return {
            FakeCv2.CAP_PROP_FOURCC: self.actual_fourcc,
            FakeCv2.CAP_PROP_FRAME_WIDTH: float(self.width),
            FakeCv2.CAP_PROP_FRAME_HEIGHT: float(self.height),
            FakeCv2.CAP_PROP_FPS: float(self.actual_fps),
        }[prop]

    def release(self):
        self.released = True


class FakeCv2:
    CAP_V4L2 = 200
    CAP_PROP_FOURCC = 6
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FPS = 5
    CAP_PROP_BUFFERSIZE = 38

    def __init__(self, actual_fourcc=fake_fourcc('YUYV'), actual_fps=30.,
                 ignore_fourcc=False, ignore_fps=False):
        self.capture = FakeCapture(actual_fourcc, actual_fps, ignore_fourcc, ignore_fps)

    def VideoCapture(self, path, backend):
        self.path, self.backend = path, backend
        return self.capture

    def VideoWriter_fourcc(self, *value):
        self.requested_fourcc = ''.join(value)
        return fake_fourcc(self.requested_fourcc)


if __name__ == '__main__':
    unittest.main()
