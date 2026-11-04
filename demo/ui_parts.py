"""Shared static console markup; live values always come from the running session."""


def header_html(role='编码端 · 第一台 Jetson'):
    return f'''<header class="masthead">
  <div class="brand">
    <div class="brand-mark" aria-hidden="true">DC<span>▮</span></div>
    <div class="brand-text">
      <div class="eyebrow">JETSON ORIN NX · DCVC-UF HT-S</div>
      <h1>低码率视频实验台</h1>
      <p>实时重建 · 同源 H.264 / H.265 对照 · 双机有线链路</p>
    </div>
  </div>
  <div class="header-meta">
    <span class="role-chip">{role}</span>
    <div class="target">
      <small>第一阶段目标</small>
      <b>360p<span>/</span>30fps</b>
      <small>端到端 ≤ 500 ms</small>
    </div>
  </div>
</header>'''


EMPTY_ICONS = {
    'original': '点击开始，开启本次实验',
    'decoded': '码流到达后在这里显示',
    'h264': '等待 H.264 硬件链路',
    'h265': '等待 H.265 硬件链路',
}


def monitor_html(kind, title, subtitle, index=None, cls=''):
    index = index or ('01' if kind == 'original' else '02')
    idle = EMPTY_ICONS.get(kind, '等待画面')
    classes = 'video-monitor' + (f' {cls}' if cls else '')
    stats = f'<div class="monitor-stats" id="stats-{kind}"></div>' if kind in ('h264', 'h265') else ''
    return f'''<section class="{classes}" data-kind="{kind}">
  <header class="preview-title">
    <div class="preview-title-main"><span class="monitor-index">{index}</span><b>{title}</b></div>
    <span class="fps-badge" id="fps-{kind}"><i aria-hidden="true"></i><em>0.0 fps</em></span>
  </header>
  <div class="video-surface">
    <canvas id="preview-{kind}" width="640" height="360" aria-label="{title}"></canvas>
    <div class="video-empty" id="empty-{kind}">
      <svg width="40" height="40" viewBox="0 0 38 38" fill="none" aria-hidden="true"><rect x="5" y="8" width="28" height="22" rx="5" stroke="currentColor" stroke-width="1.4"/><path d="m16 14 8 5-8 5V14Z" fill="currentColor"/></svg>
      <b>等待画面</b><span>{idle}</span>
    </div>
  </div>
  {stats}
  <footer class="monitor-footer"><span>{subtitle}</span><span>浏览器绘制实测</span></footer>
</section>'''
