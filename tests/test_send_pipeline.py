"""Exercise bounded full-duplex transport without CUDA or physical Ethernet."""
import socket
import threading
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from demo.config import Settings
from demo.engine import Engine
from demo.transport import recv_packet, send_packet


class SendPipelineTests(unittest.TestCase):
    def run_peer(self, handler, payload=b'compressed'):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(3)
        self.addCleanup(listener.close)
        errors = []
        def serve():
            try:
                conn, _ = listener.accept()
                with conn:
                    conn.settimeout(2)
                    handler(conn)
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        class Encoder:
            def encode(self, frames, qp):
                return {'count': len(frames)}, payload if len(frames) > 1 else b'I'
        engine = Engine(codec_factory=Encoder)
        self.addCleanup(engine.stop)
        settings = Settings(width=64, height=64, fps=120, mode='send',
                            bind='127.0.0.1', peer='127.0.0.1', port=listener.getsockname()[1])
        with patch.object(Settings, 'validate'), patch('demo.engine.ethernet_route'):
            engine.start(settings)
        return engine, thread, errors

    def wait_for(self, predicate, seconds=3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(.01)
        return False

    def test_second_group_is_sent_before_first_reply(self):
        release = threading.Event()
        self.addCleanup(release.set)
        def peer(conn):
            batches = [recv_packet(conn)[0], recv_packet(conn)[0]]
            ok, jpeg = cv2.imencode('.jpg', np.zeros((64, 64, 3), np.uint8))
            self.assertTrue(ok)
            for batch in batches:
                count = batch['count']
                send_packet(conn, {'type': 'preview', 'count': count, 'decode_ms': 1,
                                   'sizes': [len(jpeg)] * count}, jpeg.tobytes() * count)
            release.wait(3)
        engine, thread, errors = self.run_peer(peer)
        self.assertTrue(self.wait_for(lambda: engine.snapshot()['decode']['frames'] >= 9), str(errors))
        engine.stop()
        release.set()
        thread.join(3)
        self.assertFalse(errors)
        self.assertFalse(engine.alive())

    def test_stalled_peer_bounds_inflight_work_and_stop_unblocks_reader(self):
        received = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        def peer(conn):
            recv_packet(conn)
            recv_packet(conn)
            received.set()
            release.wait(3)
        engine, thread, errors = self.run_peer(peer)
        self.assertTrue(received.wait(2), str(errors))
        time.sleep(.25)
        self.assertEqual(engine.snapshot()['encode']['frames'], 9)
        self.assertGreater(engine.snapshot()['dropped'], 0)
        engine.stop()
        self.assertTrue(self.wait_for(lambda: not engine.alive(), 1))
        self.assertEqual(engine.snapshot()['state'], 'idle')
        release.set()
        thread.join(3)
        self.assertFalse(errors)

    def test_bad_reply_remains_visible_and_worker_exits(self):
        def peer(conn):
            recv_packet(conn)
            send_packet(conn, {'type': 'preview', 'count': 99}, b'bad')
        engine, thread, errors = self.run_peer(peer)
        self.assertTrue(self.wait_for(lambda: not engine.alive()))
        self.assertEqual(engine.snapshot()['state'], 'error')
        self.assertIn('无效帧数', engine.snapshot()['message'])
        thread.join(3)
        self.assertFalse(errors)

    def test_bad_reply_interrupts_blocked_writer_and_preserves_cause(self):
        release = threading.Event()
        self.addCleanup(release.set)
        def peer(conn):
            recv_packet(conn)
            # Ensure the writer begins its next large group before rejecting the first.
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            time.sleep(.2)
            send_packet(conn, {'type': 'preview', 'count': 99}, b'bad')
            release.wait(3)
        engine, thread, errors = self.run_peer(peer, b'x' * (16 * 1024 * 1024))
        self.assertTrue(self.wait_for(lambda: not engine.alive(), 1.5))
        self.assertEqual(engine.snapshot()['state'], 'error')
        self.assertIn('无效帧数', engine.snapshot()['message'])
        release.set()
        thread.join(3)
        self.assertFalse(errors)
