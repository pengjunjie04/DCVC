import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from demo import hardware_compare


class HardwareCompareTests(unittest.TestCase):
    def test_encoder_keeps_local_and_remote_capture_times_separate(self):
        encoder = hardware_compare.HardwareEncoder('127.0.0.1', 4, 2, 30, 250)
        payload = bytes(range(24))
        encoder.push(np.frombuffer(payload, dtype=np.uint8).reshape(2, 4, 3), 111, 222)
        packet = encoder.write_queue.get_nowait()
        magic, local_ns, remote_ns, width, height, size = hardware_compare.INPUT_HEADER.unpack_from(packet)
        self.assertEqual((magic, local_ns, remote_ns, width, height, size),
                         (b'HWF1', 111, 222, 4, 2, len(payload)))
        self.assertEqual(packet[hardware_compare.INPUT_HEADER.size:], payload)

    def test_frame_file_round_trip_and_corruption_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(hardware_compare, 'FRAME_DIR', root):
                jpeg = b'\xff\xd8test\xff\xd9'
                data = hardware_compare.FRAME_HEADER.pack(b'HWF1', 17, 123456789, len(jpeg)) + jpeg
                (root / 'dcvc-hw-h264.frame').write_bytes(data)
                self.assertEqual(hardware_compare.read_frame('h264'), (17, 123456789, jpeg))
                (root / 'dcvc-hw-h265.frame').write_bytes(data[:-1])
                self.assertIsNone(hardware_compare.read_frame('h265'))
                self.assertIsNone(hardware_compare.read_frame('other'))

    def test_stats_merge_keeps_both_codecs_available(self):
        stats = hardware_compare.WorkerStats()
        stats.update({'type':'event', 'message':'connected'})
        stats.update({'type':'stats', 'codecs':{
            'h264':{'fps':30.0, 'kbps':250.0, 'latency_ms':18.0, 'connected':True},
            'h265':{'fps':29.0, 'kbps':210.0, 'latency_ms':22.0, 'connected':True},
        }})
        snapshot = stats.snapshot()
        self.assertTrue(snapshot['h264']['available'])
        self.assertEqual(snapshot['h264']['kbps'], 250.0)
        self.assertEqual(snapshot['h265']['latency_ms'], 22.0)
        self.assertEqual(snapshot['messages'], ['connected'])

    def test_invalid_stats_are_ignored(self):
        stats = hardware_compare.WorkerStats()
        stats.update({'type':'stats', 'codecs':'bad'})
        self.assertFalse(stats.snapshot()['h264']['available'])


if __name__ == '__main__':
    unittest.main()
