/* Decoder display console behavior. */
const sparkPreview = new Sparkline('spark-preview', '#76e3b4');
const sparkEncode = new Sparkline('spark-encode', '#7db9ff');
const sparkDecode = new Sparkline('spark-decode', '#f3bd63');
const sparkBitrate = new Sparkline('spark-bitrate', '#76e3b4');
const chartLatency = new SeriesChart('chart-latency', [
  {color: '#76e3b4'},
  {color: '#f3bd63'},
], {limit: 90});

function updateState(state) {
  DCVC.state = state;
  DCVC.running = state.state === 'running' || state.state === 'starting';
  const settings = state.settings || {};
  const preview = state.preview || {};
  const encode = state.encode || {};
  const decode = state.decode || {};
  const timing = state.timing || {};
  const processing = state.processing || {};
  const stateName = state.state || 'waiting';

  setStatus(`${stateLabel(stateName)} · ${state.message || ''}`, stateName);
  if (settings.width) {
    setText('stage-res', `${settings.width} × ${settings.height} · ${settings.fps}fps`);
    setText('session-path', `${settings.width} × ${settings.height} · ${settings.fps} fps · QP ${settings.qp} · 第二台 Jetson 解码显示`);
  } else {
    setText('stage-res', '等待码流');
  }

  const previewFps = preview.fps;
  const encodeFps = encode.fps;
  const decodeFps = decode.fps;
  const modelKbps = encode.mbps === undefined ? null : encode.mbps * 1000;
  setMetric('metric-preview', number(previewFps, 1));
  setMetric('metric-encode', number(encodeFps, 1));
  setMetric('metric-decode', number(decodeFps, 1));
  setMetric('metric-bitrate', number(modelKbps, 1));

  sparkPreview.push(previewFps);
  sparkEncode.push(encodeFps);
  sparkDecode.push(decodeFps);
  sparkBitrate.push(modelKbps);

  const median = timing.capture_to_canvas_median_ms;
  const p95 = timing.capture_to_canvas_p95_ms;
  const max = timing.capture_to_canvas_max_ms;
  setText('latency-badge', median === null || median === undefined ? '—' : `${number(median, 0)} ms`);
  setText('lat-median', median === null || median === undefined ? '—' : `${number(median, 1)} ms`);
  setText('lat-p95', p95 === null || p95 === undefined ? '—' : `${number(p95, 1)} ms`);
  setText('lat-samples', integer(timing.capture_to_canvas_samples));
  setText('display-queue', integer(state.display_queue));
  setText('display-age', state.display_oldest_age_ms === null || state.display_oldest_age_ms === undefined ? '—' : `${number(state.display_oldest_age_ms, 0)} ms`);
  setText('drop-preview', integer(state.preview_dropped));
  setText('decode-processing', processing.decode?.fps ? `${number(processing.decode.fps, 1)} fps` : '—');
  setText('encode-processing', processing.encode?.fps ? `${number(processing.encode.fps, 1)} fps` : '—');
  setText('decode-frames', integer(decode.frames));
  setText('bitrate-detail', modelKbps === null ? '—' : `${number(modelKbps, 1)} kbps`);
  chartLatency.push([median, p95]);

  const dropNode = document.getElementById('drop-preview');
  if (dropNode) dropNode.className = Number(state.preview_dropped) > 0 ? 'bad' : 'good';
  const maxNode = document.getElementById('lat-p95');
  if (maxNode) maxNode.className = p95 !== null && p95 !== undefined && Number(p95) > 500 ? 'bad' : 'good';

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
    setStatus('解码服务已退出或连接中断', 'offline');
  } finally {
    polling = false;
  }
}

function setupDecoder() {
  $('#quit').addEventListener('click', async () => {
    if (!window.confirm('退出接收程序？当前解码会话会结束。')) return;
    try {
      await api('/api/control/quit', {method: 'POST', headers: {'X-Demo-Request': '1'}});
      setStatus('接收程序已退出', 'offline');
      toast('解码端已退出', 'success');
    } catch (error) { toast(error.message, 'error'); }
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  setupCommon();
  setupDecoder();
  startFrameLoop({kind: 'decoded', canvasId: 'preview-decoded', fpsId: 'fps-decoded', stale: true});
  await pollState();
  setInterval(pollState, 1000);
});
