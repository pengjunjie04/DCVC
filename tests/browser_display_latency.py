"""Opt-in real-camera, dual-Jetson capture-to-canvas acceptance; saves statistics only."""
import glob
import json
import os
import re
import statistics
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get('DCVC_ENCODER_URL', 'http://127.0.0.1:7860')
DECODER_PAGE = os.environ.get('DCVC_DECODER_PAGE_URL', 'http://127.0.0.1:7861')
DECODER_API = os.environ.get('DCVC_DECODER_API_URL', DECODER_PAGE)
DECODER_CDP = os.environ['DCVC_DECODER_CDP']
result = {
    'scope': 'USB camera capture completion on encoder -> official DCVC-UF HT-S -> Ethernet TCP -> independent decoder -> JPEG preview IPC -> actual canvas drawImage() in Chromium on the second Jetson. Software timestamps, not physical screen/glass-to-glass. No image or video saved.',
    'measurement': 'Per-frame capture timestamp is translated to the decoder clock with NTP-style round trips; the decoder browser reports performance.timeOrigin + performance.now() immediately after canvas drawImage().',
    'settings': {'width':640, 'height':360, 'fps':30, 'qp':32},
    'browser_errors': [],
    'samples': [],
}


def overcurrent_counts():
    return {path:int(Path(path).read_text()) for path in glob.glob('/sys/class/hwmon/hwmon*/oc*_event_cnt')}


power_mode = subprocess.check_output(['nvpmodel','-q'], text=True).strip()
required_mode = os.environ.get('DCVC_REQUIRE_POWER_MODE')
if required_mode and ('NV Power Mode: '+required_mode) not in power_mode:
    raise RuntimeError('Requested power mode is not active: '+power_mode)
initial_oc = overcurrent_counts()
result['encoder_hardware'] = {'power_mode':power_mode, 'overcurrent_before':initial_oc}


def check_overcurrent():
    current = overcurrent_counts()
    if any(current.get(path, count) > count for path, count in initial_oc.items()):
        raise RuntimeError('New overcurrent event detected; stopping the hardware test')


def percentile(values, fraction):
    values = sorted(values)
    return values[max(0, min(len(values)-1, int(len(values)*fraction + .999999)-1))]


with sync_playwright() as p:
    control_browser = p.chromium.launch(executable_path='/snap/bin/chromium', headless=True,
                                        args=['--no-sandbox','--disable-gpu'])
    page = control_browser.new_page(viewport={'width':1440,'height':1100})
    page.on('pageerror', lambda error:result['browser_errors'].append('encoder: '+str(error)))
    decoder_browser = p.chromium.connect_over_cdp(DECODER_CDP)
    decoder_page = decoder_browser.contexts[0].pages[0]
    decoder_page.bring_to_front()
    decoder_page.on('pageerror', lambda error:result['browser_errors'].append('decoder: '+str(error)))
    result['decoder_browser_location'] = 'actual second Jetson desktop Chromium via CDP'

    def decoder_request(path):
        return decoder_page.request.get(DECODER_API + path).json()
    def encoder_state():
        return page.request.get(BASE + '/api/state').json()
    def wait_for_running(frames=121, timeout=180):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            check_overcurrent()
            state = encoder_state()
            if state['state'] == 'error':
                raise RuntimeError(state['message'])
            if state['state'] == 'running' and state['decode']['frames'] >= frames:
                return state
            page.wait_for_timeout(200)
        raise TimeoutError('Dual-host decoded frame deadline exceeded')
    try:
        decoder_page.goto(DECODER_PAGE, wait_until='domcontentloaded')
        if decoder_request('/api/state')['role'] != 'decoder':
            raise RuntimeError('Decoder page did not expose decoder API')
        page.goto(BASE, wait_until='domcontentloaded')
        page.get_by_label('运行模式', exact=True).click()
        page.get_by_role('option').filter(has_text='双机发送').click()
        page.get_by_label('视频源', exact=True).click()
        page.get_by_role('option').filter(has_text='USB 摄像头').click()
        page.get_by_text('设备与有线网络', exact=True).click()
        page.get_by_label('本机有线 IPv4', exact=True).fill('192.168.50.1')
        page.get_by_label('解码端有线 IPv4', exact=True).fill('192.168.50.2')
        page.get_by_role('button', name='▶ 开始', exact=True).click()
        state = wait_for_running()
        result['encoder_steady_start'] = state
        result['decoder_steady_start'] = decoder_request('/api/state')
        start_decoder_us = int(decoder_page.evaluate('Date.now() * 1e3'))
        collected = {}
        for second in range(40):
            page.wait_for_timeout(1000)
            check_overcurrent()
            report = decoder_request('/api/latency')
            for sample in report['samples']:
                if sample['draw_unix_us'] >= start_decoder_us:
                    collected[sample['sequence']] = sample
            result['samples'].append({'second':second+1, 'encoder':encoder_state(),
                                      'latency_summary':report['summary']})
            if second % 10 == 9:
                payload = {'second':second+1, 'latency_count':len(collected),
                           'median_ms':result['samples'][-1]['latency_summary']['median_ms'],
                           'browser_fps':decoder_page.locator('#fps-decoded').inner_text()}
                print(json.dumps(payload, ensure_ascii=False), flush=True)
        latency = [sample['latency_ms'] for sample in collected.values()]
        if len(latency) < 600:
            raise RuntimeError(f'Too few browser draw samples: {len(latency)}')
        summary = {'count':len(latency), 'median_ms':statistics.median(latency),
                   'p95_ms':percentile(latency, .95), 'min_ms':min(latency), 'max_ms':max(latency)}
        result['latency_summary'] = summary
        result['latency_samples'] = sorted(collected.values(), key=lambda sample:sample['sequence'])
        result['browser_draw_fps'] = decoder_page.locator('#fps-decoded').inner_text()
        final = encoder_state()
        result['encoder_steady_end'] = final
        result['decoder_steady_end'] = decoder_request('/api/state')
        result['target_checks'] = {
            'median_capture_to_canvas_at_most_500ms': summary['median_ms'] <= 500,
            'p95_capture_to_canvas_at_most_500ms': summary['p95_ms'] <= 500,
            'max_sampled_capture_to_canvas_at_most_500ms': summary['max_ms'] <= 500,
            'clock_sync_available': bool(final.get('clock_sync')),
            'physical_glass_to_glass_latency': 'not measured',
        }
        result['clock_sync'] = final.get('clock_sync')
        failed_targets = [name for name, passed in result['target_checks'].items() if passed is False]
        if failed_targets or result['browser_errors']:
            raise RuntimeError('Acceptance failed: ' + ', '.join(failed_targets + result['browser_errors']))
        page.get_by_role('button', name='■ 结束', exact=True).click()
        deadline = time.monotonic() + 30
        while encoder_state()['worker_alive'] and time.monotonic() < deadline:
            page.wait_for_timeout(100)
        result['status'] = 'passed'
    except Exception as exc:
        result['status'] = 'failed'
        result['error'] = str(exc)
        print('ERROR:', exc, flush=True)
        try:
            page.request.post(BASE + '/api/control/stop', headers={'X-Demo-Request':'1'})
        except Exception:
            pass
        raise
    finally:
        result['encoder_hardware']['overcurrent_after'] = overcurrent_counts()
        (ROOT/'reports'/'browser-display-latency-25w.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        control_browser.close()
print(json.dumps({key:result.get(key) for key in
                  ('status','latency_summary','target_checks','clock_sync','browser_draw_fps','browser_errors')},
                 ensure_ascii=False, indent=2), flush=True)
