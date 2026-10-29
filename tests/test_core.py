import socket
import struct
import threading
import unittest

from demo.config import Settings
from demo.metrics import WindowStats
from demo.transport import recv_packet, send_packet
from demo.codec import validate_packet


class ConfigTests(unittest.TestCase):
    def test_codec_rejects_bad_metadata_and_accepts_eight_entropy_streams(self):
        good = {'type': 'P', 'width': 640, 'height': 360, 'qp': 32, 'ec': 8, 'reset': 0, 'count': 8}
        validate_packet(good, b'abc')
        for update in ({'count': 9}, {'width': 999999}, {'ec': 9}, {'qp': -1}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_packet({**good, **update}, b'abc')

    def test_reject_invalid_before_allocating_resources(self):
        for fields in ({'fps': 0}, {'fps': 121}, {'qp': 64}, {'width': 0},
                       {'width': 10000}, {'mode': 'unknown'}, {'port': 0},
                       {'source': 'unknown'}, {'fps': float('nan')}, {'qp': 1.5}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                Settings(**fields).validate()

    def test_sender_requires_explicit_wired_addresses(self):
        with self.assertRaises(ValueError):
            Settings(mode='send').validate()
        Settings(mode='send', bind='192.168.50.1', peer='192.168.50.2').validate()


class TransportTests(unittest.TestCase):
    def test_fragmented_packet_and_non_ascii_metadata(self):
        a, b = socket.socketpair()
        try:
            def write():
                send_packet(a, {'type': 'I', 'label': '测试'}, b'\x00\x12\xff')
            t = threading.Thread(target=write)
            t.start()
            meta, payload = recv_packet(b)
            t.join()
            self.assertEqual(meta, {'type': 'I', 'label': '测试'})
            self.assertEqual(payload, b'\x00\x12\xff')
        finally:
            a.close()
            b.close()

    def test_short_reads(self):
        a, b = socket.socketpair()
        try:
            data = b'DCV1' + struct.pack('!II', 12, 3) + b'{"type":"I"}' + b'abc'
            def write():
                for byte in data:
                    a.sendall(bytes([byte]))
            t = threading.Thread(target=write)
            t.start()
            self.assertEqual(recv_packet(b), ({'type': 'I'}, b'abc'))
            t.join()
        finally:
            a.close()
            b.close()

    def test_unbounded_length_rejected_without_payload(self):
        a, b = socket.socketpair()
        try:
            a.sendall(b'DCV1' + struct.pack('!II', 99999999, 0))
            with self.assertRaises(ValueError):
                recv_packet(b)
        finally:
            a.close()
            b.close()

    def test_truncated_packet_is_not_silently_accepted(self):
        a, b = socket.socketpair()
        try:
            a.sendall(b'DCV1' + struct.pack('!II', 2, 4) + b'{}x')
            a.shutdown(socket.SHUT_WR)
            with self.assertRaises(EOFError):
                recv_packet(b)
        finally:
            a.close()
            b.close()

    def test_non_object_json_rejected(self):
        a, b = socket.socketpair()
        try:
            a.sendall(b'DCV1' + struct.pack('!II', 2, 0) + b'[]')
            with self.assertRaises(ValueError):
                recv_packet(b)
        finally:
            a.close()
            b.close()


class RateTests(unittest.TestCase):
    def test_rates_include_elapsed_time_and_decay_after_stall(self):
        now = [0.0]
        stats = WindowStats(seconds=2, clock=lambda: now[0])
        now[0] = 1.0
        stats.add(frames=30, size=125000)
        self.assertEqual(stats.snapshot(), {'fps': 30.0, 'mbps': 1.0, 'frames': 30, 'bytes': 125000})
        now[0] = 4.0
        self.assertEqual(stats.snapshot(), {'fps': 0.0, 'mbps': 0.0, 'frames': 30, 'bytes': 125000})


if __name__ == '__main__':
    unittest.main()
