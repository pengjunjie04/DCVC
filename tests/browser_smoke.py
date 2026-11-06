"""Manual integration command: .env/bin/python -s tests/browser_smoke.py."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
BASE = os.environ.get('DCVC_ENCODER_URL', 'http://127.0.0.1:7860')
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path=os.environ.get('DCVC_CHROMIUM', '/snap/bin/chromium'), headless=True,
                                         args=['--no-sandbox', '--disable-gpu'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1100}, device_scale_factor=1)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(BASE + '/', wait_until='domcontentloaded')
    page.get_by_text('运行设置', exact=True).wait_for()
    page.get_by_label('运行模式', exact=True).select_option('capture')
    page.get_by_label('视频源', exact=True).select_option('synthetic')
    page.get_by_role('button', name='▶ 开始', exact=True).click()
    page.wait_for_function("document.getElementById('fps-original').textContent !== '0.0 fps'")
    page.wait_for_timeout(2000)
    state = page.request.get(BASE + '/api/state').json()
    assert state['capture']['frames'] > 20, state
    assert state['encode']['frames'] == 0, state
    capture_browser_fps = page.locator('#fps-original').inner_text()
    page.screenshot(path=str(root / 'reports' / 'ui-capture.png'), full_page=True)
    page.get_by_role('button', name='Ⅱ 暂停', exact=True).click()
    page.wait_for_function("document.getElementById('live-status').textContent.startsWith('PAUSED')")
    page.get_by_role('button', name='▷ 继续', exact=True).click()
    page.wait_for_function("document.getElementById('live-status').textContent.startsWith('RUNNING')")
    page.get_by_role('button', name='■ 结束', exact=True).click()
    page.wait_for_function("document.getElementById('live-status').textContent.startsWith('IDLE')")
    report = {'capture_state': state, 'browser_original_fps_during_capture': capture_browser_fps,
              'browser_errors': errors, 'lifecycle': 'start / pause / resume / stop succeeded'}
    (root / 'reports' / 'browser-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    assert not errors, errors
    browser.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
