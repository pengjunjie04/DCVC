"""Opt-in real camera / wired dual-Jetson browser acceptance; start both services first. Saves statistics only."""
import json, time, statistics
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:7860'
result={'scope':'USB camera -> official DCVC-UF HT-S encoder on 192.168.50.1 -> TCP eno1 -> independent decoder on 192.168.50.2 -> JPEG preview -> encoder browser. No video or screenshots saved. Latency is camera capture to returned preview, excluding browser rendering; not one-way glass-to-glass.', 'settings':{'width':640,'height':360,'fps':30,'qp':32}, 'samples':[], 'browser_errors':[]}
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/snap/bin/chromium',headless=True,args=['--no-sandbox','--disable-gpu'])
    page=browser.new_page(viewport={'width':1440,'height':1100})
    page.on('pageerror',lambda e:result['browser_errors'].append(str(e)))
    def state(): return page.request.get(BASE+'/api/state').json()
    def wait_frames(n, timeout=180):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            s=state()
            if s['state']=='error': raise RuntimeError(s['message'])
            if s['state']=='running' and s['decode']['frames']>=n: return s
            page.wait_for_timeout(200)
        raise TimeoutError('Dual-host decoded frame deadline exceeded')
    def idle():
        deadline=time.monotonic()+30
        while state()['worker_alive']:
            if time.monotonic()>deadline: raise TimeoutError('Worker did not release')
            page.wait_for_timeout(100)
    try:
        page.goto(BASE,wait_until='domcontentloaded')
        page.get_by_label('运行模式',exact=True).click()
        page.get_by_role('option').filter(has_text='双机发送').click()
        page.get_by_label('视频源',exact=True).click()
        page.get_by_role('option').filter(has_text='USB 摄像头').click()
        page.get_by_text('设备与有线网络',exact=True).click()
        page.get_by_label('本机有线 IPv4',exact=True).fill('192.168.50.1')
        page.get_by_label('解码端有线 IPv4',exact=True).fill('192.168.50.2')
        page.get_by_role('button',name='▶ 开始',exact=True).click()
        wait_frames(121)
        initial=state(); t0=time.monotonic()
        result['steady_start']=initial
        for i in range(60):
            page.wait_for_timeout(1000)
            s=state()
            if s['state']=='error': raise RuntimeError(s['message'])
            result['samples'].append({'elapsed':time.monotonic()-t0,'state':s,'browser_fps':{k:page.locator('#fps-'+k).inner_text() for k in ('original','decoded')}})
            if i%10==9: print(json.dumps({'second':i+1,'capture_fps':s['capture']['fps'],'decode_fps':s['decode']['fps'],'latency_ms':s['timing'].get('oldest_to_host_ms'),'drops':s['dropped'],'browser':result['samples'][-1]['browser_fps']}),flush=True)
        last=state(); elapsed=time.monotonic()-t0
        assert last['decode']['frames'] > initial['decode']['frames'], 'Decoded frames stalled'
        result['steady_summary']={'seconds':elapsed,**{k+'_fps':(last[k]['frames']-initial[k]['frames'])/elapsed for k in ('capture','encode','decode','preview')},'model_mbps':(last['encode']['bytes']-initial['encode']['bytes'])*8/elapsed/1e6,'input_drops':last['dropped']-initial['dropped'],'preview_drops':last['preview_dropped']-initial['preview_dropped'],'latency_median_ms':statistics.median(x['state']['timing']['oldest_to_host_ms'] for x in result['samples']),'latency_max_sample_ms':max(x['state']['timing']['oldest_to_host_ms'] for x in result['samples'])}
        page.get_by_role('button',name='Ⅱ 暂停',exact=True).click()
        page.wait_for_function("document.getElementById('live-status').textContent.startsWith('PAUSED')")
        idle()
        assert state()['state']=='paused'
        before=state()['capture']['frames']; page.wait_for_timeout(1000); assert state()['capture']['frames']==before
        page.get_by_role('button',name='▷ 继续',exact=True).click()
        result['resumed_state']=wait_frames(33)
        page.get_by_role('button',name='■ 结束',exact=True).click()
        page.wait_for_function("document.getElementById('live-status').textContent.startsWith('IDLE')")
        idle()
        assert state()['state']=='idle'
        page.get_by_role('button',name='保存本次统计',exact=True).click()
        page.get_by_text('统计报告（不含视频）',exact=True).wait_for()
        assert not result['browser_errors'],result['browser_errors']
        result['target_checks']={'steady_decode_at_least_29_5fps':result['steady_summary']['decode_fps']>=29.5,
            'all_sampled_return_latencies_at_most_500ms':result['steady_summary']['latency_max_sample_ms']<=500,
            'glass_to_glass_latency':'not measured'}
        result['status']='passed'; result['lifecycle']='start / pause / resume with fresh decoded frames / end / export succeeded'
    except Exception as exc:
        result['status']='failed'; result['error']=str(exc)
        print('ERROR:',exc,flush=True)
        try: page.request.post(BASE+'/api/control/stop',headers={'X-Demo-Request':'1'})
        except Exception: pass
        raise
    finally:
        (ROOT/'reports'/'dual-host-camera-browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        browser.close()
print(json.dumps({k:v for k,v in result.items() if k in ('status','steady_summary','target_checks','lifecycle','browser_errors')},ensure_ascii=False),flush=True)
