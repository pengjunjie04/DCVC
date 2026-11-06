/* Encoder console behavior. */
const RESOLUTIONS = {
  '240p': [416, 240],
  '360p': [640, 360],
  '480p': [832, 480],
  '720p': [1280, 720],
  '1080p': [1920, 1080],
};
const STORAGE_KEY = 'dcvc.encoder.settings.v2';
const MODE_LABELS = {send: '双机发送', local: '本机编解码', capture: '仅采集检查'};

const sparkCapture = new Sparkline('spark-capture', '#76e3b4');
const sparkEncode = new Sparkline('spark-encode', '#7db9ff');
const sparkDecode = new Sparkline('spark-decode', '#f3bd63');
const sparkBitrate = new Sparkline('spark-bitrate', '#76e3b4');
const chartThroughput = new SeriesChart('chart-throughput', [
  {color: '#76e3b4'},
  {color: '#7db9ff'},
  {color: '#f3bd63'},
], {limit: 90});
const chartLatency = new SeriesChart('chart-latency', [
  {color: '#76e3b4'},
  {color: '#7db9ff'},
], {limit: 90});

function readForm() {
  return {
    mode: $('#mode').value,
    source: $('#source').value,
    resolution: $('#resolution').value,
    fps: Number($('#fps').value),
    qp: Number($('#qp').value),
    camera: $('#camera').value.trim(),
    bind: $('#bind').value.trim(),
    peer: $('#peer').value.trim(),
    port: Number($('#port').value),
  };
}

function buildSettings() {
  const form = readForm();
  const [width, height] = RESOLUTIONS[form.resolution] || RESOLUTIONS['360p'];
  return {
    width, height, fps: form.fps, qp: form.qp,
    mode: form.mode, source: form.source,
    camera: form.camera, bind: form.bind, peer: form.peer, port: form.port,
  };
}

function saveForm() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(readForm())); } catch (error) { /* private mode */ }
}

function restoreForm() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'); } catch (error) { /* ignore */ }
  if (!saved || typeof saved !== 'object') return;
  for (const key of ['mode', 'source', 'resolution', 'camera', 'bind', 'peer']) {
    if (saved[key] !== undefined && document.getElementById(key)) document.getElementById(key).value = saved[key];
  }
  for (const key of ['fps', 'qp', 'port']) {
    if (saved[key] !== undefined && Number.isFinite(Number(saved[key])) && document.getElementById(key)) {
      document.getElementById(key).value = saved[key];
    }
  }
}

function syncRangeLabels() {
  setText('fps-value', $('#fps').value);
  setText('qp-value', $('#qp').value);
}

function setBusy(button, busy) {
  if (button) button.disabled = busy;
}

async function runAction(action, payload = {}) {
  try {
    const state = await control(action, payload);
    updateState(state);
    saveForm();
    if (action === 'start' || action === 'apply') toast('会话已启动', 'success');
    if (action === 'pause') toast('已暂停采集', 'success');
    if (action === 'resume') toast('已继续采集', 'success');
    if (action === 'stop') toast('已结束会话', 'success');
    await pollState();
  } catch (error) {
    toast(error.message, 'error');
  }
}

function setPipe(id, value) {
  const node = document.getElementById(id);
  if (node) node.style.width = `${clamp(Number(value) || 0, 0, 100)}%`;
}

function updateState(state) {
  DCVC.state = state;
  DCVC.running = state.state === 'running' || state.state === 'starting';
  const settings = state.settings || {};
  const capture = state.capture || {};
  const encode = state.encode || {};
  const decode = state.decode || {};
  const timing = state.timing || {};
  const processing = state.processing || {};
  const clock = state.clock_sync || {};
  const stateName = state.state || 'idle';

  setStatus(`${stateLabel(stateName)} · ${state.message || ''}`, stateName);
  setText('session-badge', stateLabel(stateName));

  const mode = MODE_LABELS[settings.mode] || settings.mode || '—';
  const route = settings.mode === 'send'
    ? `${settings.bind || '编码端'} → 有线 TCP → ${settings.peer || '解码端'}`
    : settings.mode === 'capture' ? '仅采集检查' : '本机编解码';
  setText('stage-res', `${settings.width || '—'} × ${settings.height || '—'} · ${settings.fps || '—'}fps`);
  setText('session-meta', `${mode} · ${route} · QP ${settings.qp ?? '—'}`);
  setText('session-path', state.message || '等待运行');

  setMetric('metric-capture', number(capture.fps, 1));
  setMetric('metric-encode', number(encode.fps, 1));
  setMetric('metric-decode', number(decode.fps, 1));
  setMetric('metric-bitrate', number(encode.mbps === undefined ? null : encode.mbps * 1000, 1));
  setText('metric-capture-sub', `累计 ${integer(capture.frames)} 帧`);
  setText('metric-encode-sub', `处理 ${number(processing.encode?.fps, 1)} fps`);
  setText('metric-decode-sub', `处理 ${number(processing.decode?.fps, 1)} fps`);
  setText('metric-bitrate-sub', '仅模型载荷 · 2 秒窗口');

  sparkCapture.push(capture.fps);
  sparkEncode.push(encode.fps);
  sparkDecode.push(decode.fps);
  sparkBitrate.push(encode.mbps === undefined ? null : encode.mbps * 1000);
  chartThroughput.push([capture.fps, encode.fps, decode.fps]);
  chartLatency.push([timing.oldest_to_host_ms, timing.newest_to_host_ms]);

  const oldest = timing.oldest_to_host_ms;
  setText('latency-badge', oldest === undefined || oldest === null ? '—' : `${number(oldest, 0)} ms`);
  setText('lat-wait', timing.batch_wait_ms === undefined ? '—' : `${number(timing.batch_wait_ms, 0)} ms`);
  setText('lat-encode', timing.encode_group_ms === undefined ? '—' : `${number(timing.encode_group_ms, 0)} ms`);
  setText('lat-decode', timing.decode_group_ms === undefined ? '—' : `${number(timing.decode_group_ms, 0)} ms`);
  const wait = Number(timing.batch_wait_ms) || 0;
  const enc = Number(timing.encode_group_ms) || 0;
  const dec = Number(timing.decode_group_ms) || 0;
  const total = wait + enc + dec;
  setPipe('pipe-wait', total ? wait / total * 100 : 0);
  setPipe('pipe-encode', total ? enc / total * 100 : 0);
  setPipe('pipe-decode', total ? dec / total * 100 : 0);
  setText('pipeline-total', total ? `${number(total, 0)} ms` : '—');
  setText('encode-processing', processing.encode?.fps ? `${number(processing.encode.fps, 1)} fps` : '—');
  setText('decode-processing', processing.decode?.fps ? `${number(processing.decode.fps, 1)} fps` : '—');

  setText('frames-count', `${integer(capture.frames)} / ${integer(encode.frames)}`);
  setText('drop-capture', integer(state.dropped));
  setText('drop-preview', integer(state.preview_dropped));
  setText('clock-offset', clock.offset_ms === undefined ? '—' : `${number(clock.offset_ms, 1)} ms / ${number(clock.rtt_ms, 2)} ms`);
  setText('worker-state', state.worker_alive ? '运行中' : '已停止');
  const worker = document.getElementById('worker-state');
  if (worker) worker.className = state.worker_alive ? 'good' : '';
  const clockNode = document.getElementById('clock-offset');
  if (clockNode) clockNode.className = state.clock_sync ? 'good' : '';

  const stageClock = document.getElementById('stage-clock');
  if (stageClock) stageClock.textContent = `更新 ${new Date().toLocaleTimeString('zh-CN', {hour12: false})}`;
}

let polling = false;
async function pollState() {
  if (polling) return;
  polling = true;
  try {
    updateState(await getJSON('/api/state'));
  } catch (error) {
    setStatus('服务已退出或连接中断', 'offline');
  } finally {
    polling = false;
  }
}

function setupControls() {
  restoreForm();
  syncRangeLabels();
  $('#fps').addEventListener('input', syncRangeLabels);
  $('#qp').addEventListener('input', syncRangeLabels);
  for (const id of ['mode', 'source', 'resolution', 'camera', 'bind', 'peer', 'port', 'fps', 'qp']) {
    document.getElementById(id)?.addEventListener('change', saveForm);
  }
  $('#start').addEventListener('click', async event => {
    setBusy(event.currentTarget, true);
    try { await runAction('start', buildSettings()); }
    finally { setBusy(event.currentTarget, false); }
  });
  $('#apply').addEventListener('click', async event => {
    setBusy(event.currentTarget, true);
    try { await runAction('start', buildSettings()); }
    finally { setBusy(event.currentTarget, false); }
  });
  $('#pause').addEventListener('click', () => runAction('pause'));
  $('#resume').addEventListener('click', () => runAction('resume'));
  $('#stop').addEventListener('click', () => runAction('stop'));
  $('#quit').addEventListener('click', async () => {
    if (!window.confirm('退出编码端程序？当前采集会停止。')) return;
    try {
      await control('quit');
      setStatus('程序已退出；重新运行启动脚本即可打开', 'offline');
      toast('编码端已退出', 'success');
    } catch (error) { toast(error.message, 'error'); }
  });
  $$('[data-dialog-open="devices-dialog"]').forEach(button => button.addEventListener('click', refreshDevices));
  document.addEventListener('keydown', event => {
    if (event.key === 'f' && !event.target.matches('input, select, textarea')) {
      $('[data-action="focus"]')?.click();
    }
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  setupCommon();
  setupControls();
  startFrameLoop({kind: 'original', canvasId: 'preview-original', fpsId: 'fps-original'});
  await pollState();
  await refreshDevices(true);
  setInterval(pollState, 1000);
});
