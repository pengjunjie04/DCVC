"""Shared static console markup; live values always come from the running session."""

def header_html(role='编码端 · 第一台 Jetson'):
    return f'''<div class="masthead"><div></div>
    <div class="header-meta"><span class="role-chip">{role}</span><div class="target"><small>第一阶段目标 · 实测验收</small><b>360p <span>/</span> 30 fps</b><small>延迟目标 ≤500ms</small></div></div></div>'''



def monitor_html(kind, title, subtitle):
    index = '01' if kind == 'original' else '02'
    return f'''<section class="video-monitor"><div class="preview-title"><div><span class="monitor-index">{index}</span><b>{title}</b></div>
    <span class="fps-badge" id="fps-{kind}">0.0 fps</span></div><div class="video-surface"><canvas id="preview-{kind}" width="640" height="360" aria-label="{'原始' if kind == 'original' else '解码'}视频画面"></canvas>
    <div class="video-empty" id="empty-{kind}"><svg width="38" height="38" viewBox="0 0 38 38" fill="none" aria-hidden="true"><rect x="5" y="8" width="28" height="22" rx="5" stroke="currentColor" stroke-width="1.5"/><path d="m16 14 8 5-8 5V14Z" fill="currentColor"/></svg>
    <b>等待{'采集' if kind == 'original' else '解码'}画面</b><span>{'点击开始，开启本次实验' if kind == 'original' else '码流到达后在这里显示'}</span></div></div>
    <div class="monitor-footer"><span>{subtitle}</span><span>浏览器实测 FPS ↗</span></div></section>'''
