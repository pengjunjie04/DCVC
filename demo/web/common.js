/* Shared browser helpers for the encoder and decoder consoles. */
const DCVC = window.DCVC = window.DCVC || {running: false, state: null};
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function number(value, digits = 1) {
  if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(digits);
}

function integer(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return String(Math.round(Number(value)));
}

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function setMetric(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

async function api(path, options = {}) {
  const response = await fetch(path, {cache: 'no-store', ...options});
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || body.message || detail;
    } catch (error) { /* keep status text */ }
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response;
}

async function getJSON(path) {
  return (await api(path)).json();
}

async function control(action, payload = {}) {
  const response = await api('/api/control/' + action, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Demo-Request': '1'},
    body: JSON.stringify(payload),
  });
  return response.json();
}

function toast(message, kind = '') {
  let stack = document.getElementById('toast-stack');
  if (!stack) {
    stack = document.createElement('div');
    stack.id = 'toast-stack';
    stack.className = 'toast-stack';
    document.body.append(stack);
  }
  const node = document.createElement('div');
  node.className = 'toast ' + kind;
  node.textContent = message;
  stack.append(node);
  setTimeout(() => node.remove(), 5200);
}

function setStatus(text, state) {
  const node = document.getElementById('live-status');
  if (node) {
    node.textContent = text;
    node.dataset.state = state || '';
  }
  const pill = document.getElementById('connection-pill');
  if (pill) {
    pill.dataset.state = state || '';
    const label = $('#connection-text');
    if (label) label.textContent = ({running:'运行中', starting:'初始化', paused:'已暂停', error:'异常', offline:'离线', idle:'待机', waiting:'等待连接'})[state] || '待机';
  }
}

function stateLabel(state) {
  return (state || 'idle').toUpperCase();
}

function renderDevices(data, rootId = 'device-list') {
  const root = document.getElementById(rootId);
  if (!root) return;
  const labels = {摄像头: '摄像头', 本机IPv4: '本机 IPv4', 模型: '模型', 第二台: '解码端', 验收目标: '验收目标'};
  root.replaceChildren();
  for (const [key, value] of Object.entries(data || {})) {
    const row = document.createElement('div');
    row.className = 'device-row';
    const title = document.createElement('b');
    title.textContent = labels[key] || key;
    const body = document.createElement('span');
    body.textContent = Array.isArray(value) ? value.join('；') : String(value);
    row.append(title, body);
    root.append(row);
  }
}

async function downloadReport() {
  const response = await api('/api/report', {method: 'POST', headers: {'X-Demo-Request': '1'}});
  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const matched = /filename=\"?([^\";]+)\"?/.exec(disposition);
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = matched ? matched[1] : 'dcvc-report.json';
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  toast('统计报告已下载', 'success');
}

/* ---------- charts ---------- */

class SeriesChart {
  constructor(canvas, series, options = {}) {
    this.canvas = typeof canvas === 'string' ? document.getElementById(canvas) : canvas;
    this.series = series.map(item => ({...item, values: []}));
    this.limit = options.limit || 90;
    this.min = options.min;
    this.max = options.max;
    this.suffix = options.suffix || '';
    if (!this.canvas) return;
    this.resizeObserver = new ResizeObserver(() => this.draw());
    this.resizeObserver.observe(this.canvas);
  }

  push(values) {
    if (!this.canvas) return;
    for (let index = 0; index < this.series.length; index += 1) {
      const value = values[index];
      this.series[index].values.push(Number.isFinite(Number(value)) ? Number(value) : NaN);
      if (this.series[index].values.length > this.limit) this.series[index].values.shift();
    }
    this.draw();
  }

  draw() {
    const canvas = this.canvas;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.round(rect.width * dpr);
    const height = Math.round(rect.height * dpr);
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);

    const all = this.series.flatMap(item => item.values).filter(Number.isFinite);
    if (!all.length) {
      ctx.strokeStyle = 'rgba(126,146,159,.2)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, rect.height / 2);
      ctx.lineTo(rect.width, rect.height / 2);
      ctx.stroke();
      return;
    }
    let min = this.min === undefined ? Math.min(...all) : this.min;
    let max = this.max === undefined ? Math.max(...all) : this.max;
    if (max - min < 0.5) { max = min + 1; }
    min = Math.max(0, min - (max - min) * .12);
    max = max + (max - min) * .12;

    const pad = {top: 8, right: 8, bottom: 8, left: 8};
    const chartWidth = rect.width - pad.left - pad.right;
    const chartHeight = rect.height - pad.top - pad.bottom;
    const xAt = index => pad.left + (this.limit <= 1 ? 0 : index / (this.limit - 1) * chartWidth);
    const yAt = value => pad.top + chartHeight - ((value - min) / (max - min)) * chartHeight;

    ctx.strokeStyle = 'rgba(126,146,159,.12)';
    ctx.lineWidth = 1;
    for (let line = 0; line < 4; line += 1) {
      const y = pad.top + chartHeight * line / 3;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(rect.width - pad.right, y);
      ctx.stroke();
    }

    for (const item of this.series) {
      const values = item.values;
      if (!values.length) continue;
      const offset = this.limit - values.length;
      const points = [];
      values.forEach((value, index) => {
        if (Number.isFinite(value)) points.push([xAt(offset + index), yAt(value)]);
      });
      if (points.length === 1) {
        ctx.fillStyle = item.color;
        ctx.beginPath();
        ctx.arc(points[0][0], points[0][1], 2.4, 0, Math.PI * 2);
        ctx.fill();
        continue;
      }
      if (points.length) {
        ctx.beginPath();
        points.forEach(([x, y], index) => index ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
        ctx.lineWidth = 2;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        ctx.strokeStyle = item.color;
        ctx.stroke();
        if (item.fill) {
          const gradient = ctx.createLinearGradient(0, pad.top, 0, rect.height);
          gradient.addColorStop(0, item.color + '30');
          gradient.addColorStop(1, item.color + '00');
          ctx.lineTo(points[points.length - 1][0], rect.height - pad.bottom);
          ctx.lineTo(points[0][0], rect.height - pad.bottom);
          ctx.closePath();
          ctx.fillStyle = gradient;
          ctx.fill();
        }
        const last = points[points.length - 1];
        ctx.fillStyle = item.color;
        ctx.beginPath();
        ctx.arc(last[0], last[1], 2.8, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }
}

class Sparkline extends SeriesChart {
  constructor(canvas, color = '#76e3b4') {
    super(canvas, [{color, fill: true}], {limit: 60});
  }
  push(value) { super.push([value]); }
}

/* ---------- frame stream ---------- */

function copyToLightbox(canvas) {
  const lightbox = document.getElementById('lightbox');
  if (!lightbox || lightbox.hidden) return;
  const target = document.getElementById('lightbox-canvas');
  if (!target) return;
  if (target.width !== canvas.width || target.height !== canvas.height) {
    target.width = canvas.width;
    target.height = canvas.height;
  }
  target.getContext('2d').drawImage(canvas, 0, 0);
}

function startFrameLoop({kind, canvasId, fpsId, stale = false, onDraw = null}) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const fpsNode = document.getElementById(fpsId);
  let sequence = -1;
  let drawn = 0;
  let started = performance.now();
  let pendingDraws = [];
  let staleDropped = 0;
  const abort = new AbortController();

  async function reportDraws() {
    if (!stale || (!pendingDraws.length && !staleDropped)) return;
    const samples = pendingDraws.splice(0, 120);
    try {
      await fetch('/api/preview/drawn', {
        method: 'POST',
        cache: 'no-store',
        signal: abort.signal,
        headers: {'Content-Type': 'application/json', 'X-Demo-Request': '1'},
        body: JSON.stringify({samples, dropped: Math.min(120, staleDropped)}),
      });
    } catch (error) { /* decoder may be quitting */ }
    staleDropped = 0;
  }

  (async () => {
    while (!abort.signal.aborted) {
      const tick = performance.now();
      try {
        const response = await fetch(`/api/frame/${kind}?after=${sequence}`, {cache: 'no-store', signal: abort.signal});
        if (response.status === 200) {
          const frameSequence = Number(response.headers.get('X-Sequence'));
          const captureNs = Number(response.headers.get('X-Capture-Unix-Ns'));
          const captureUs = Number.isFinite(captureNs) ? Math.round(captureNs / 1000) : NaN;
          sequence = frameSequence;
          const receivedUs = Math.round((performance.timeOrigin + performance.now()) * 1000);
          const isStale = stale && Number.isFinite(captureUs) && receivedUs - captureUs > 495000;
          if (isStale) {
            staleDropped += 1;
          } else {
            const image = await createImageBitmap(await response.blob());
            if (canvas.width !== image.width || canvas.height !== image.height) {
              canvas.width = image.width;
              canvas.height = image.height;
            }
            canvas.getContext('2d').drawImage(image, 0, 0);
            const empty = document.getElementById('empty-' + kind);
            if (empty) empty.hidden = true;
            copyToLightbox(canvas);
            const drawUs = Math.round((performance.timeOrigin + performance.now()) * 1000);
            if (stale && Number.isFinite(captureUs) && drawUs > captureUs) {
              pendingDraws.push([frameSequence, captureUs, drawUs]);
            }
            image.close();
            drawn += 1;
            if (onDraw) onDraw({sequence: frameSequence, captureUs, drawUs});
          }
        } else if (response.status === 204 && !DCVC.running) {
          sequence = 0;
        }
      } catch (error) {
        if (abort.signal.aborted) return;
      }
      const now = performance.now();
      if (now - started >= 1000) {
        if (fpsNode) fpsNode.textContent = (drawn * 1000 / (now - started)).toFixed(1) + ' fps';
        drawn = 0;
        started = now;
        reportDraws();
      }
      await sleep(Math.max(0, (DCVC.running ? 8 : 120) - (performance.now() - tick)));
    }
  })();
}

/* ---------- lightbox / fullscreen / dialogs ---------- */

function setupLightbox(title) {
  const lightbox = document.getElementById('lightbox');
  if (!lightbox) return;
  const stage = $('.stage-card');
  const zoomLabel = document.getElementById('zoom-label');
  const stageCanvas = $('.stage-body canvas');
  const zoomStage = document.getElementById('lightbox-stage');
  let zoom = 1;
  let dragging = false;
  let dragStart = null;

  function setZoom(next, anchor = null) {
    const old = zoom;
    zoom = clamp(next, 0.5, 4);
    const canvas = document.getElementById('lightbox-canvas');
    if (canvas) canvas.style.width = `${zoom * 100}%`;
    if (zoomLabel) zoomLabel.textContent = `${zoom.toFixed(1)}×`;
    if (anchor && zoomStage) {
      const ratio = zoom / old;
      zoomStage.scrollLeft = (zoomStage.scrollLeft + anchor.x) * ratio - anchor.x;
      zoomStage.scrollTop = (zoomStage.scrollTop + anchor.y) * ratio - anchor.y;
    }
  }

  function open() {
    lightbox.hidden = false;
    document.body.classList.add('lightbox-open');
    const heading = document.getElementById('lightbox-title');
    if (heading) heading.textContent = title || '画面预览';
    if (stageCanvas) copyToLightbox(stageCanvas);
    setZoom(1);
    if (zoomStage) { zoomStage.scrollLeft = 0; zoomStage.scrollTop = 0; }
  }

  function close() {
    lightbox.hidden = true;
    document.body.classList.remove('lightbox-open');
  }

  $$('[data-action="expand"]').forEach(button => button.addEventListener('click', open));
  $$('[data-action="fullscreen"]').forEach(button => button.addEventListener('click', async () => {
    if (!stage) return;
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await stage.requestFullscreen();
    } catch (error) {
      toast('浏览器拒绝了全屏请求', 'error');
    }
  }));
  $$('[data-action="focus"]').forEach(button => button.addEventListener('click', () => {
    document.body.classList.toggle('focus-mode');
    const active = document.body.classList.contains('focus-mode');
    button.setAttribute('aria-pressed', String(active));
    button.querySelector('span').textContent = active ? '退出影院' : '影院模式';
  }));
  $$('[data-lightbox-close]').forEach(button => button.addEventListener('click', close));
  $$('[data-zoom]').forEach(button => button.addEventListener('click', () => setZoom(zoom + Number(button.dataset.zoom))));
  const reset = document.querySelector('[data-zoom-reset]');
  if (reset) reset.addEventListener('click', () => setZoom(1));
  lightbox.addEventListener('click', event => { if (event.target === lightbox) close(); });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !lightbox.hidden) close();
  });
  if (zoomStage) {
    zoomStage.addEventListener('wheel', event => {
      event.preventDefault();
      const rect = zoomStage.getBoundingClientRect();
      setZoom(zoom - event.deltaY * .001, {x: event.clientX - rect.left, y: event.clientY - rect.top});
    }, {passive: false});
    zoomStage.addEventListener('pointerdown', event => {
      if (event.button !== 0 || zoom <= 1) return;
      dragging = true;
      dragStart = {x: event.clientX, y: event.clientY, left: zoomStage.scrollLeft, top: zoomStage.scrollTop};
      zoomStage.setPointerCapture(event.pointerId);
    });
    zoomStage.addEventListener('pointermove', event => {
      if (!dragging || !dragStart) return;
      zoomStage.scrollLeft = dragStart.left - (event.clientX - dragStart.x);
      zoomStage.scrollTop = dragStart.top - (event.clientY - dragStart.y);
    });
    const stopDrag = () => { dragging = false; dragStart = null; };
    zoomStage.addEventListener('pointerup', stopDrag);
    zoomStage.addEventListener('pointercancel', stopDrag);
  }
}

function setupDialogs() {
  $$('[data-dialog-open]').forEach(button => button.addEventListener('click', () => {
    const dialog = document.getElementById(button.dataset.dialogOpen);
    if (dialog) {
      if (button.dataset.dialogOpen === 'details-dialog') {
        const pre = document.getElementById('details-json');
        if (pre) pre.textContent = JSON.stringify(DCVC.state || {}, null, 2);
      }
      dialog.showModal();
    }
  }));
  $$('[data-dialog-close]').forEach(button => button.addEventListener('click', () => button.closest('dialog')?.close()));
  $$('dialog').forEach(dialog => dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  }));
}

async function refreshDevices(silent = false) {
  try {
    renderDevices(await getJSON('/api/devices'));
    if (!silent) toast('设备状态已刷新', 'success');
  } catch (error) {
    if (!silent) toast('无法读取设备状态：' + error.message, 'error');
  }
}

function setupReportButton() {
  $$('[data-action="report"]').forEach(button => button.addEventListener('click', async () => {
    button.disabled = true;
    try { await downloadReport(); }
    catch (error) { toast('导出失败：' + error.message, 'error'); }
    finally { button.disabled = false; }
  }));
}

function setupCommon() {
  setupLightbox(document.body.dataset.previewTitle || '画面预览');
  setupDialogs();
  setupReportButton();
  $$('[data-action="refresh"]').forEach(button => button.addEventListener('click', refreshDevices));
  const footerYear = document.getElementById('footer-year');
  if (footerYear) footerYear.textContent = new Date().getFullYear();
}
