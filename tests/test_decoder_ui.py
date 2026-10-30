import time
import unittest
from fastapi.testclient import TestClient
from demo.decoder_ui import DecoderMonitor, create_decoder_app


class DecoderDisplayTests(unittest.TestCase):
    def test_eight_frames_are_paced_on_decoder_and_no_image_is_written(self):
        monitor = DecoderMonitor()
        self.addCleanup(monitor.close)
        monitor.begin_session()
        frames = [b'jpeg-' + bytes([i]) for i in range(8)]
        monitor.accept({'width':640,'height':360,'fps':30,'qp':32,'encode_fps':30,
                        'encode_ms':40,'decode_ms':80,'total_frames':8,'total_bytes':128}, frames)
        deadline = time.monotonic() + 1
        while monitor.snapshot()['preview']['frames'] < 8 and time.monotonic() < deadline:
            time.sleep(.01)
        state = monitor.snapshot()
        self.assertEqual(state['decode']['frames'], 8)
        self.assertEqual(state['preview']['frames'], 8)
        self.assertEqual(monitor.image()[1], frames[-1])
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
                            'encode_ms':None,'decode_ms':1,'total_frames':1,'total_bytes':5}, [b'actual-jpeg'])
            deadline = time.monotonic() + 1
            while monitor.image()[1] is None and time.monotonic() < deadline:
                time.sleep(.01)
            response = client.get('/api/frame/decoded')
            self.assertEqual(response.content, b'actual-jpeg')
            self.assertEqual(client.get('/api/frame/decoded', params={'after':response.headers['X-Sequence']}).status_code, 204)
            self.assertEqual(client.post('/api/control/quit').status_code, 403)
            self.assertEqual(client.post('/api/control/quit', headers={'X-Demo-Request':'1'}).status_code, 200)
            self.assertTrue(monitor.exit_requested.is_set())
