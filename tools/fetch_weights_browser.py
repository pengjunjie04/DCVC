"""Download only the two requested official files, using anonymous public OneDrive UI."""
import hashlib
import json
import os
from pathlib import Path
import urllib.request
import urllib.parse
import shutil
import base64
import subprocess
import tempfile
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://1drv.ms/f/c/2866592d5c55df8c/IgAalzb_985lQ79GkXyW2P5OASPpZHHcrcGWEVQxO-mQCVg?e=qyvMN6'
names = ['cvpr2026_image.pth.tar', 'cvpr2026_video_hts.pth.tar']
folder = ROOT / 'checkpoints'
folder.mkdir(exist_ok=True)
records = []
with sync_playwright() as p:
    launch_options = {
        'executable_path': os.environ.get('DCVC_CHROMIUM', '/snap/bin/chromium'),
        'headless': True,
        'args': ['--no-sandbox', '--disable-gpu'],
    }
    proxy = os.environ.get('DCVC_PROXY', 'http://127.0.0.1:7897').strip()
    if proxy:
        launch_options['proxy'] = {'server': proxy}
    browser = p.chromium.launch(**launch_options)
    page = browser.new_page(accept_downloads=True)
    download_requests = {}
    def remember_download(request):
        if 'download.aspx' in request.url:
            download_requests[request.url] = (request.method, request.post_data, request.all_headers())
    page.on('request', remember_download)
    for attempt in range(3):
        try:
            # Resolve the short URL with Python; Chromium's short-link navigation can stall.
            resolved = 'https://onedrive.live.com/?' + urllib.parse.urlencode({
                'id': '2866592D5C55DF8C!sff36971acef74365bf46917c96d8fe4e',
                'cid': '2866592D5C55DF8C',
                'spopath': '2866592D5C55DF8C!sff36971acef74365bf46917c96d8fe4e',
                'listurl': '/personal/2866592d5c55df8c/Documents', 'e': 'qyvMN6',
                'redeem': base64.urlsafe_b64encode(URL.encode()).decode().rstrip('='),
                'reauth': '1', 'ga': '1'})
            try:
                page.goto(URL if attempt % 2 == 0 else resolved, wait_until='domcontentloaded', timeout=30000)
            except Exception:
                pass  # OneDrive redirects may interrupt navigation while the file table still loads.
            page.get_by_text(names[0], exact=True).wait_for(timeout=60000)
            break
        except Exception as exc:
            try:
                print(type(exc).__name__, page.title(), page.locator('body').inner_text(timeout=3000)[:1200], flush=True)
            except Exception:
                print(type(exc).__name__, 'OneDrive page unavailable', flush=True)
            if attempt == 2:
                raise
            print('Retrying public OneDrive folder', flush=True)
    for name in names:
        destination = folder / name
        if not destination.exists() or destination.stat().st_size == 0:
            print(f'Downloading official {name}', flush=True)
            page.get_by_text(name, exact=True).click(button='right')
            with page.expect_download(timeout=60000) as event:
                page.get_by_role('menu').get_by_role('menuitem', name='Download', exact=True).click()
            download = event.value
            part = destination.with_suffix('.tar.part')
            link = urllib.parse.urlparse(download.url)
            print(f'Official download endpoint: {link.scheme}://{link.hostname}', flush=True)
            if link.scheme == 'https':
                download.cancel()
                with tempfile.NamedTemporaryFile(mode='w', prefix='dcvc-public-cookies-') as cookie_file:
                    cookie_file.write('# Netscape HTTP Cookie File\n')
                    for cookie in page.context.cookies():
                        cookie_file.write('\t'.join([cookie['domain'], 'TRUE' if cookie['domain'].startswith('.') else 'FALSE',
                            cookie['path'], 'TRUE' if cookie['secure'] else 'FALSE', '0', cookie['name'], cookie['value']]) + '\n')
                    cookie_file.flush()
                    method, body, headers = download_requests.get(download.url, ('GET', None, {}))
                    print('Download request method:', method, 'body bytes:', len(body or ''), flush=True)
                    args = ['curl', '--http1.1', '-fLsS', '--retry', '2', '--retry-all-errors',
                        '--connect-timeout', '20', '--max-time', '600', '--cookie', cookie_file.name,
                        '--referer', page.url, '--user-agent', page.evaluate('navigator.userAgent'),
                        '--request', method, '--output', str(part)]
                    if part.exists() and part.stat().st_size:
                        args += ['--continue-at', '-']
                    if body is not None:
                        args += ['--data-binary', '@-']
                    if 'content-type' in headers:
                        args += ['--header', 'Content-Type: ' + headers['content-type']]
                    subprocess.run(args + [download.url], input=body, text=True, check=True)
            else:
                download.save_as(part)
                if download.failure():
                    raise RuntimeError(download.failure())
            if part.stat().st_size < 100 * 1024 * 1024:
                raise RuntimeError('Official weight download was incomplete')
            destination.with_suffix('.tar.part').replace(destination)
            if destination.stat().st_size == 0:
                raise RuntimeError('Official download returned an empty file; retry required')
        digest = hashlib.file_digest(destination.open('rb'), 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else hashlib.sha256(destination.read_bytes()).hexdigest()
        records.append({'name': name, 'bytes': destination.stat().st_size, 'sha256': digest, 'source_folder': URL})
        print(f'Saved {name}: {destination.stat().st_size} bytes', flush=True)
    browser.close()
(ROOT / 'reports' / 'official-weight-downloads.json').write_text(json.dumps(records, indent=2))
