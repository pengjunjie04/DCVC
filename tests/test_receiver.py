from io import BytesIO
import math
import multiprocessing
import os
import socket
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image
from demo.receiver import serve_session
from demo.transport import decode_preview, send_packet


class CrashCodec:
    def decode(self, packet):
        os._exit(73)


class HungCodec:
    def decode(self, packet):
        time.sleep(10)


class FailedCodec:
    def decode(self, packet):
        raise RuntimeError('model unavailable')


class ReceiverTests(unittest.TestCase):
    def test_model_error_is_visible_in_decoder_monitor(self):
        from demo.decoder_ui import DecoderMonitor
        monitor = DecoderMonitor()
        a, b = socket.socketpair()
        send_packet(b, {'type':'I','width':640,'height':360,'qp':32,'ec':1,'reset':0,'count':1}, b'1234')
        try:
            with patch('demo.receiver.Codec', FailedCodec):
                code = serve_session(a, context=multiprocessing.get_context('fork'), monitor=monitor)
            self.assertNotEqual(code, 0)
            self.assertEqual(monitor.snapshot()['state'], 'error')
        finally:
            a.close()
            b.close()
            monitor.close()

    def test_hung_native_session_is_terminated(self):
        a, b = socket.socketpair()
        send_packet(b, {'type': 'I', 'width': 640, 'height': 360, 'qp': 32, 'ec': 1, 'reset': 0, 'count': 1}, b'1234')
        try:
            started = time.monotonic()
            with patch('demo.receiver.Codec', HungCodec):
                code = serve_session(a, context=multiprocessing.get_context('fork'), silence_timeout=.1)
            self.assertLess(time.monotonic() - started, 2)
            self.assertNotEqual(code, 0)
        finally:
            a.close()
            b.close()

    def test_native_session_crash_does_not_kill_listener_process(self):
        a, b = socket.socketpair()
        meta = {'type': 'I', 'width': 640, 'height': 360, 'qp': 32, 'ec': 1, 'reset': 0, 'count': 1}
        send_packet(b, meta, b'1234')
        try:
            # Fork only in this CPU-only test so the crash codec exists in the child.
            # The real receiver uses spawn because CUDA must not be initialized after fork.
            with patch('demo.receiver.Codec', CrashCodec):
                code = serve_session(a, context=multiprocessing.get_context('fork'))
            self.assertEqual(code, 73)
            self.assertGreater(os.getpid(), 0)
        finally:
            a.close()
            b.close()

    def test_preview_requires_finite_timing_and_expected_image_dimensions(self):
        stream = BytesIO()
        Image.new('RGB', (64, 64), (12, 34, 56)).save(stream, format='JPEG')
        data = stream.getvalue()
        meta = {'type': 'preview', 'count': 1, 'sizes': [len(data)], 'decode_ms': 5.0}
        frames, elapsed = decode_preview(meta, data, 1, 64, 64)
        self.assertEqual(frames[0].shape, (64, 64, 3))
        self.assertEqual(elapsed, 5.0)
        for value in (math.nan, math.inf, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_preview({**meta, 'decode_ms': value}, data, 1, 64, 64)
        with self.assertRaises(ValueError):
            decode_preview(meta, data, 1, 640, 360)


if __name__ == '__main__':
    unittest.main()
