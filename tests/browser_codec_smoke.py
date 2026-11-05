"""Real pretrained local-pipeline browser integration; server must be running."""
import json
from pathlib import Path
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/snap/bin/chromium', headless=True,
                                args=['--no-sandbox', '--disable-gpu'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:7860/', wait_until='domcontentloaded')
    page.get_by_label('运行模式',exact=True).click()
    page.get_by_role('option').filter(has_text='本机编解码').click()
    page.get_by_label('视频源',exact=True).click()
    page.get_by_role('option').filter(has_text='测试图案').click()
    page.get_by_role('button', name='▶ 开始', exact=True).click()
    def wait_frames(count):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            state = page.request.get('http://127.0.0.1:7860/api/state').json()
            if state['state'] == 'error':
                raise RuntimeError(state['message'])
            if state['decode']['frames'] >= count:
                return state
            page.wait_for_timeout(100)
        raise TimeoutError('Pretrained pipeline did not produce the expected frames')
    wait_frames(90)
    samples = []
    for _ in range(10):
        samples.append(page.request.get('http://127.0.0.1:7860/api/state').json())
        page.wait_for_timeout(500)
    browser_fps = {'original': page.locator('#fps-original').inner_text()}
    assert page.locator('#fps-decoded').count() == 0, 'encoder page must not show a DCVC reconstruction monitor'
    page.screenshot(path=str(ROOT / 'reports' / 'ui-codec.png'), full_page=True)
    page.get_by_role('button', name='保存本次统计', exact=True).click()
    page.get_by_text('统计报告（不含视频）', exact=True).wait_for()
    assert samples[-1]['encode']['frames'] > 100
    assert samples[-1]['decode']['frames'] > 100
    assert samples[-1]['encode']['bytes'] > 0
    page.get_by_role('button', name='Ⅱ 暂停', exact=True).click()
    page.wait_for_function("document.getElementById('live-status').textContent.startsWith('PAUSED')")
    page.get_by_role('button', name='▷ 继续', exact=True).click()
    page.wait_for_function("document.getElementById('live-status').textContent.startsWith('RUNNING')")
    wait_frames(17)
    page.get_by_role('button', name='■ 结束', exact=True).click()
    page.wait_for_function("document.getElementById('live-status').textContent.startsWith('IDLE')")
    result = {'scope': 'Official pretrained HT-S local round-trip on generated input, Gradio browser lifecycle; not USB/dual-host acceptance',
              'status': 'passed', 'samples': samples, 'browser_fps': browser_fps, 'browser_errors': errors}
    (ROOT / 'reports' / 'browser-codec-smoke.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    assert not errors, errors
    browser.close()
    print(json.dumps({'status':'passed','browser_fps':browser_fps,'last_sample':samples[-1]}, ensure_ascii=False))
