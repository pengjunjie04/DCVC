"""Synthetic-only visual/layout check. Never saves camera imagery."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get('DCVC_ENCODER_URL','http://127.0.0.1:7860')
DECODER=os.environ.get('DCVC_DECODER_PAGE_URL','http://127.0.0.1:17861')
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('DCVC_CHROMIUM', '/snap/bin/chromium'), headless=True,args=['--no-sandbox','--disable-gpu'])
    page=browser.new_page(viewport={'width':1440,'height':1050})
    errors=[]
    page.on('pageerror', lambda e:errors.append(str(e)))
    page.goto(BASE, wait_until='domcontentloaded')
    page.get_by_label('运行模式', exact=True).select_option('capture')
    page.get_by_label('视频源', exact=True).select_option('synthetic')
    page.get_by_role('button',name='▶ 开始',exact=True).click()
    page.wait_for_function("document.getElementById('live-status').dataset.state==='running'")
    page.wait_for_function("document.getElementById('empty-original').hidden")
    page.wait_for_timeout(1500)
    page.screenshot(path=str(ROOT/'reports/console-encoder.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    page.wait_for_timeout(500)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'), 'Mobile horizontal overflow'
    page.screenshot(path=str(ROOT/'reports/console-mobile.png'),full_page=True)
    page.get_by_role('button',name='■ 结束',exact=True).click()
    page.wait_for_function("document.getElementById('live-status').dataset.state==='idle'")
    dec=browser.new_page(viewport={'width':1440,'height':1100})
    dec.on('pageerror',lambda e:errors.append(str(e)))
    dec.goto(DECODER,wait_until='domcontentloaded')
    dec.locator('.metric-card').first.wait_for()
    dec.screenshot(path=str(ROOT/'reports/console-decoder-waiting.png'),full_page=True)
    assert not errors,errors
    print(json.dumps({'status':'passed','mobile_no_horizontal_overflow':True,'browser_errors':errors}))
    browser.close()
