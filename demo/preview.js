() => {
  if (window.dcvcPreviewController) window.dcvcPreviewController.abort();
  const controller = new AbortController();
  window.dcvcPreviewController = controller;
  const signal = controller.signal;
  let running = false;
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
              if (canvas.width !== image.width || canvas.height !== image.height) {
                canvas.width = image.width; canvas.height = image.height;
              }
              canvas.getContext('2d').drawImage(image, 0, 0);
              image.close();
              const empty = document.getElementById('empty-' + kind);
              if (empty) empty.hidden = true;
              seq = Number(response.headers.get('X-Sequence'));
              drawn++;
            } else if (response.status === 204 && !running) {
              seq = 0;
            }
          }
        } catch (e) { if (signal.aborted) return; }
        const now = performance.now();
        if (now - started >= 1000) {
          const label = document.getElementById('fps-' + kind);
          if (label) label.textContent = (drawn * 1000 / (now - started)).toFixed(1) + ' fps';
          drawn = 0; started = now;
        }
        await pause(Math.max(0, (running ? 15 : 100) - (performance.now() - tick)));
      }
    })();
  }
  let metricNodes = [];
  (async () => {
    while (!signal.aborted) {
      try {
        const res = await fetch('/api/state', {cache:'no-store', signal});
        if (!res.ok) throw new Error('state unavailable');
        const s = await res.json();
        running = s.state === 'running' || s.state === 'starting';
        const text = document.getElementById('live-status');
        const states = {idle:'就绪',waiting:'等待连接',starting:'初始化',running:'运行中',paused:'已暂停',error:'异常'};
        if (text) {
          text.textContent = s.state.toUpperCase() + ' · ' + (states[s.state] || '') + ' · ' + s.message;
          text.dataset.state = s.state;
        }
        const path = document.getElementById('session-path');
        if (path) {
          const p = s.settings;
          const route = p.mode === 'send' ? (p.bind || '编码端') + ' → 有线 TCP → ' + (p.peer || '解码端') : p.mode === 'capture' ? '仅采集检查' : '本机编解码';
          path.textContent = `${p.width} × ${p.height}  ·  目标 ${p.fps} fps  ·  QP ${p.qp}  ·  ${route}`;
        }
        const remote = s.role === 'decoder';
        const processing = s.processing || {};
        const cards = [
          [remote ? '显示吞吐' : '采集吞吐', remote ? s.preview.fps : s.capture.fps, 2, 'fps'],
          ['编码吞吐',s.encode.fps,2,'fps'],['解码吞吐',s.decode.fps,2,'fps'],['模型码率',s.encode.mbps,3,'Mbps'],
          ['编码处理速度',processing.encode?.fps,1,'fps','compute'],['解码处理速度',processing.decode?.fps,1,'fps','compute'],
          remote ? ['画面尺寸',`${s.settings.width}×${s.settings.height}`,null,'px'] :
            [s.settings.mode === 'send' ? '往返预览耗时' : '采集至解码',s.timing.oldest_to_host_ms,1,'ms'],
          [remote ? '展示丢帧 · 累计' : '采集丢帧 · 累计',remote ? s.preview_dropped : s.dropped,0,'帧']
        ];
        const el = document.getElementById('live-metrics');
        if (el) {
          if (metricNodes.length !== cards.length || !metricNodes[0]?.card.isConnected) {
            metricNodes = cards.map(() => {
              const card = document.createElement('div');
              const label = document.createElement('small');
              const line = document.createElement('b');
              const detail = document.createElement('small'); detail.className = 'compute-detail';
              const num = document.createElement('span');
              const unit = document.createElement('span'); unit.className = 'unit';
              line.append(num,unit); card.append(label,line,detail);
              return {card,label,num,unit,detail};
            });
            el.replaceChildren(...metricNodes.map(n => n.card));
          }
          cards.forEach(([name,value,digits,unit,style],i) => {
            const node = metricNodes[i];
            node.card.className = 'metric' + (style ? ' ' + style : '');
            node.label.textContent = name;
            node.num.textContent = value == null ? '—' : digits == null ? value : Number(value).toFixed(digits);
            node.unit.textContent = unit;
            node.detail.hidden = style !== 'compute';
            node.detail.textContent = style === 'compute' && Number(value)>0 ? (1000/Number(value)).toFixed(2)+' ms/帧' : '等待计时';
          });
        }
      } catch(e) {
        if (signal.aborted) return;
        running = false;
        const el = document.getElementById('live-status');
        if (el) { el.dataset.state = 'offline'; el.textContent = '服务已退出或连接中断；重新运行启动脚本即可打开。'; }
      }
      await pause(1000);
    }
  })();
}
