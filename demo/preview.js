() => {
  if (window.dcvcPreviewController) window.dcvcPreviewController.abort();
  const controller = new AbortController();
  window.dcvcPreviewController = controller;
  const signal = controller.signal;
  const pause = ms => new Promise(r => setTimeout(r, ms));
  for (const kind of ['original', 'decoded']) {
    (async () => {
      let seq = -1, drawn = 0, started = performance.now();
      while (!signal.aborted) {
        const tick = performance.now();
        try {
          const canvas = document.getElementById('preview-' + kind);
          if (canvas) {
            const response = await fetch('/api/frame/' + kind + '?after=' + seq, {cache:'no-store', signal});
            if (response.status === 200) {
              const image = await createImageBitmap(await response.blob());
              canvas.width = image.width; canvas.height = image.height;
              canvas.getContext('2d').drawImage(image, 0, 0);
              image.close();
              seq = Number(response.headers.get('X-Sequence'));
              drawn++;
            }
          }
        } catch (e) { if (signal.aborted) return; }
        const now = performance.now();
        if (now - started >= 1000) {
          const label = document.getElementById('fps-' + kind);
          if (label) label.textContent = (drawn * 1000 / (now - started)).toFixed(1) + ' fps';
          drawn = 0; started = now;
        }
        await pause(Math.max(0, 30 - (performance.now() - tick)));
      }
    })();
  }
  (async () => {
    while (!signal.aborted) {
      try {
        const res = await fetch('/api/state', {cache:'no-store', signal});
        const s = await res.json();
        const text = document.getElementById('live-status');
        if (text) text.textContent = s.state.toUpperCase() + ' · ' + s.message;
        const el = document.getElementById('live-metrics');
        const cards = [['采集 fps',s.capture.fps],['编码 fps',s.encode.fps],['解码 fps',s.decode.fps],['压缩 Mbps',s.encode.mbps]];
        if (el) {
          el.replaceChildren(...cards.map(([name,value]) => {
            const card = document.createElement('div'); card.className = 'metric';
            const label = document.createElement('small'); label.textContent = name;
            const num = document.createElement('b'); num.textContent = Number(value).toFixed(2);
            card.append(label,num); return card;
          }));
        }
      } catch(e) {
        const el = document.getElementById('live-status');
        if (el) el.textContent = '服务已退出或连接中断；重新运行启动脚本即可打开。';
      }
      await pause(1000);
    }
  })();
}
