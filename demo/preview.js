() => {
  if (window.dcvcPreviewController) window.dcvcPreviewController.abort();
  const controller = new AbortController();
  window.dcvcPreviewController = controller;
  const signal = controller.signal;
  let running = false;
  const pendingDraws = [];
  let staleDropped = 0;
  const pause = ms => new Promise(r => setTimeout(r, ms));
  for (const kind of ['original', 'decoded', 'h264', 'h265']) {
    (async () => {
      let seq = -1, drawn = 0, started = performance.now();
      while (!signal.aborted) {
        const tick = performance.now();
        try {
          const canvas = document.getElementById('preview-' + kind);
          if (canvas) {
            const response = await fetch('/api/frame/' + kind + '?after=' + seq, {cache:'no-store', signal});
            if (response.status === 200) {
              const frameSeq = Number(response.headers.get('X-Sequence'));
              const captureUs = Math.round(Number(response.headers.get('X-Capture-Unix-Ns')) / 1e3);
              seq = frameSeq;
              const receivedUs = Math.round((performance.timeOrigin + performance.now()) * 1e3);
              const stale = kind === 'decoded' && Number.isSafeInteger(captureUs) && captureUs > 0 &&
                            receivedUs - captureUs > 475_000;
              if (stale) {
                staleDropped++;
              } else {
                const image = await createImageBitmap(await response.blob());
                if (canvas.width !== image.width || canvas.height !== image.height) {
                  canvas.width = image.width; canvas.height = image.height;
                }
                canvas.getContext('2d').drawImage(image, 0, 0);
                const drawUs = Math.round((performance.timeOrigin + performance.now()) * 1e3);
                image.close();
                const empty = document.getElementById('empty-' + kind);
                if (empty) empty.hidden = true;
                drawn++;
                if (kind === 'decoded' && Number.isSafeInteger(captureUs) && captureUs > 0 &&
                    Number.isSafeInteger(drawUs) && drawUs > captureUs) {
                  pendingDraws.push([frameSeq, captureUs, drawUs]);
                }
              }
            } else if (response.status === 204 && !running) {
              seq = 0;
            }
          }
        } catch (e) { if (signal.aborted) return; }
        const now = performance.now();
        if (now - started >= 1000) {
          const label = document.getElementById('fps-' + kind);
          if (label) label.textContent = (drawn * 1000 / (now - started)).toFixed(1) + ' fps';
          if (kind === 'decoded' && (pendingDraws.length || staleDropped)) {
            const samples = pendingDraws.splice(0, 120);
            fetch('/api/preview/drawn', {method:'POST', cache:'no-store', signal,
              headers:{'Content-Type':'application/json', 'X-Demo-Request':'1'},
              body:JSON.stringify({samples, dropped:staleDropped})}).catch(() => {});
            staleDropped = 0;
          }
          drawn = 0; started = now;
        }
        await pause(Math.max(0, (running ? 8 : 100) - (performance.now() - tick)));
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
        const hardware = s.hardware || {};
        const cards = [
          [remote ? '显示吞吐' : '采集吞吐', remote ? s.preview.fps : s.capture.fps, 2, 'fps'],
          ['编码吞吐',s.encode.fps,2,'fps'],['解码吞吐',s.decode.fps,2,'fps'],['模型码率',s.encode.mbps == null ? null : s.encode.mbps * 1000,2,'kbps'],
          ['编码处理速度',processing.encode?.fps,1,'fps','compute'],['解码处理速度',processing.decode?.fps,1,'fps','compute'],
          remote ? ['采集→canvas 中位数',s.timing.capture_to_canvas_median_ms,1,'ms'] :
            [s.settings.mode === 'send' ? '往返预览耗时' : '采集至解码',s.timing.oldest_to_host_ms,1,'ms'],
          [remote ? '展示丢帧 · 累计' : '采集丢帧 · 累计',remote ? s.preview_dropped : s.dropped,0,'帧'],
          ['H.264 码率',hardware.h264?.kbps,0,'kbps'],
          ['H.264 端到端',hardware.h264?.latency_ms,0,'ms'],
          ['H.265 码率',hardware.h265?.kbps,0,'kbps'],
          ['H.265 端到端',hardware.h265?.latency_ms,0,'ms'],
          ['H.264 吞吐',hardware.h264?.fps,1,'fps'],
          ['H.265 吞吐',hardware.h265?.fps,1,'fps']
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
