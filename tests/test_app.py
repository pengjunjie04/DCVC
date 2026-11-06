import time
import unittest
from fastapi.testclient import TestClient

from demo.app import create_app
from demo.engine import Engine


class AppTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()
        self.client = TestClient(create_app(self.engine, mount_ui=False))

    def tearDown(self):
        self.engine.stop()
        self.client.close()

    def test_controls_require_custom_header(self):
        response = self.client.post('/api/control/start', json={'mode': 'capture'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.engine.alive())

    def test_capture_api_preview_pause_stop(self):
        headers = {'X-Demo-Request': '1'}
        response = self.client.post('/api/control/start', headers=headers, json={'mode': 'capture'})
        self.assertEqual(response.status_code, 200)
        deadline = time.monotonic() + 3
        while self.engine.image('original')[1] is None and time.monotonic() < deadline:
            time.sleep(.03)
        image = self.client.get('/api/frame/original')
        self.assertEqual(image.status_code, 200)
        self.assertTrue(image.content.startswith(b'\xff\xd8'))
        seq = image.headers['X-Sequence']
        self.client.post('/api/control/pause', headers=headers, json={})
        last = self.client.get('/api/frame/original').headers['X-Sequence']
        self.assertEqual(self.client.get('/api/frame/original', params={'after': last}).status_code, 204)
        self.client.post('/api/control/stop', headers=headers, json={})
        self.assertEqual(self.client.get('/api/state').json()['state'], 'idle')

    def test_bad_settings_return_actionable_error(self):
        response = self.client.post('/api/control/start', headers={'X-Demo-Request': '1'}, json={'fps': 0})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.engine.alive())

    def test_report_download_and_static_ui(self):
        response = self.client.post('/api/report', headers={'X-Demo-Request': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response.headers.get('content-disposition', ''))
        self.assertIn('report-', response.headers.get('content-disposition', ''))
        app = create_app(self.engine, mount_ui=True)
        with TestClient(app) as client:
            page = client.get('/')
            self.assertEqual(page.status_code, 200)
            self.assertIn('Neural Video Link', page.text)
            self.assertEqual(client.get('/assets/style.css').status_code, 200)


if __name__ == '__main__':
    unittest.main()
