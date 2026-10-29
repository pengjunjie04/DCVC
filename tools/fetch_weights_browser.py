"""Download only the two requested official files, using anonymous public OneDrive UI."""
import hashlib
import json
from pathlib import Path
import urllib.request
import urllib.parse
import shutil
import base64
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://1drv.ms/f/c/2866592d5c55df8c/IgAalzb_985lQ79GkXyW2P5OASPpZHHcrcGWEVQxO-mQCVg?e=qyvMN6'
names = ['cvpr2026_image.pth.tar', 'cvpr2026_video_hts.pth.tar']
folder = ROOT / 'checkpoints'
folder.mkdir(exist_ok=True)
records = []
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/snap/bin/chromium', headless=True,
        args=['--no-sandbox', '--disable-gpu'], proxy={'server':'http://127.0.0.1:7897'})
    page = browser.new_page(accept_downloads=True)
    for attempt in range(3):
        try:
            # Resolve the short URL with Python; Chromium's short-link navigation can stall.
            resolved = 'https://onedrive.live.com/?' + urllib.parse.urlencode({
                'id': '2866592D5C55DF8C!sff36971acef74365bf46917c96d8fe4e',
                'cid': '2866592D5C55DF8C',
                'redeem': base64.urlsafe_b64encode(URL.encode()).decode().rstrip('='),
                'reauth': '1', 'ga': '1'})
            page.goto(resolved, wait_until='commit', timeout=30000)
            page.get_by_text(names[0], exact=True).wait_for(timeout=30000)
            break
        except Exception:
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
                with urllib.request.urlopen(download.url, timeout=60) as response, part.open('wb') as output:
                    if 'text/html' in response.headers.get('Content-Type', ''):
                        raise RuntimeError('Official endpoint returned a web page rather than weights')
                    shutil.copyfileobj(response, output, length=1024*1024)
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
