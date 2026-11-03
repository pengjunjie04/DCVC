import time
import unittest
from fastapi.testclient import TestClient
from demo.decoder_ui import DecoderMonitor, create_decoder_app


class DecoderDisplayTests(unittest.TestCase):
    def test_eight_frame_burst_is_drained_without_building_display_backlog(self):
        monitor = DecoderMonitor()
        self.addCleanup(monitor.close)
        monitor.begin_session()
        frames = [b'jpeg-' + bytes([i]) for i in range(8)]
        capture_ns = [time.time_ns() - 100_000_000 + index * 1_000_000 for index in range(8)]
        started = time.monotonic()
        monitor.accept({'width':640,'height':360,'fps':30,'qp':32,'encode_fps':30,
                        'encode_ms':40,'decode_ms':80,'total_frames':8,'total_bytes':128,
                        'capture_times_ns':capture_ns}, frames)
        deadline = time.monotonic() + 1
        while monitor.snapshot()['preview']['frames'] < 8 and time.monotonic() < deadline:
            time.sleep(.01)
        elapsed = time.monotonic() - started
        state = monitor.snapshot()
        self.assertEqual(state['decode']['frames'], 8)
        self.assertEqual(state['preview']['frames'], 8)
        self.assertLess(elapsed, .22)
        self.assertEqual(monitor.image()[1], frames[-1])
        self.assertEqual(monitor.image()[2], capture_ns[-1])
        self.assertAlmostEqual(state['processing']['encode']['fps'], 200)
        self.assertAlmostEqual(state['processing']['decode']['fps'], 100)
        monitor.end_session(0)
        self.assertEqual(monitor.snapshot()['state'], 'waiting')

    def test_decoder_api_waits_without_camera_and_serves_actual_latest_jpeg(self):
        monitor = DecoderMonitor()
        self.addCleanup(monitor.close)
        with TestClient(create_decoder_app(monitor, mount_ui=False)) as client:
            self.assertEqual(client.get('/api/state').json()['role'], 'decoder')
            self.assertEqual(client.get('/api/frame/decoded').status_code, 204)
            monitor.begin_session()
            monitor.accept({'width':64,'height':64,'fps':30,'qp':32,
                            'encode_ms':None,'decode_ms':1,'total_frames':1,'total_bytes':5,
                            'capture_times_ns':[time.time_ns()-400_000_000]}, [b'actual-jpeg'])
            deadline = time.monotonic() + 1
            while monitor.image()[1] is None and time.monotonic() < deadline:
                time.sleep(.01)
            response = client.get('/api/frame/decoded')
            self.assertEqual(response.content, b'actual-jpeg')
            capture_ns = int(response.headers['X-Capture-Unix-Ns'])
            sequence = int(response.headers['X-Sequence'])
            capture_us = capture_ns // 1000
            draw_us = capture_us + 375_000
            self.assertEqual(client.post('/api/preview/drawn', json={'samples':[[sequence,capture_us,draw_us]]}).status_code, 403)
            accepted = client.post('/api/preview/drawn', headers={'X-Demo-Request':'1'},
                                   json={'samples':[[sequence,capture_us,draw_us]], 'dropped':2})
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual(accepted.json()['accepted'], 1)
            self.assertAlmostEqual(client.get('/api/latency').json()['summary']['median_ms'], 375.0)
            state = client.get('/api/state').json()
            self.assertAlmostEqual(state['timing']['capture_to_canvas_median_ms'], 375.0)
            self.assertEqual(state['preview_dropped'], 2)
            self.assertEqual(client.get('/api/frame/decoded', params={'after':response.headers['X-Sequence']}).status_code, 204)
            self.assertEqual(client.post('/api/control/quit').status_code, 403)
            self.assertEqual(client.post('/api/control/quit', headers={'X-Demo-Request':'1'}).status_code, 200)
            self.assertTrue(monitor.exit_requested.is_set())

    def test_stale_drop_is_counted_without_any_successful_draw(self):
        monitor = DecoderMonitor()
        self.addCleanup(monitor.close)
        monitor.begin_session()
        with TestClient(create_decoder_app(monitor, mount_ui=False)) as client:
            response = client.post('/api/preview/drawn', headers={'X-Demo-Request':'1'},
                                   json={'samples':[], 'dropped':3})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['accepted'], 0)
            self.assertEqual(client.get('/api/state').json()['preview_dropped'], 3)
