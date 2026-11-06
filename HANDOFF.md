# DCVC Jetson 项目交接说明

更新时间：2026-11-06 17:30（Asia/Shanghai）

## 1. 用户目标

当前阶段任务：

1. 移除 H.264/H.265 实时与离线对比，界面不再显示。✅ 已完成
2. 重新制作展示页面，扩大画面、支持放大/全屏、改进指标展示。✅ 已完成
3. 同步解码端并提交 GitHub。进行中

用户要求中文、直接、尽量简洁；安全第一。不要删除 `.env/`、`vendor/`、`checkpoints/`、`runs/`，不要用 `rm -rf`。停止进程优先 `kill -TERM`，只有无响应时才考虑强制终止。

## 2. 当前 Git 状态

- 仓库：`/home/jetson/Desktop/dcvc-jetson-demo`
- 分支：`main`，远端 `git@github.com:pengjunjie04/DCVC.git`
- 展示层：自定义 FastAPI + HTML/CSS/JavaScript，不再使用 Gradio
- 全量测试 **51 项通过**

## 3. 双机与环境

- 编码端：`192.168.50.1`，主机名 `yahboom`
- 解码端：`192.168.50.2`，SSH 用户 `jetson`
- 两端均为 25W 模式，Jetson Orin NX 16GB
- 项目环境：`.env/`，项目 Python 为 `.env/bin/python`
- 摄像头：编码端 `/dev/video0`，YUYV 640×480@30，程序保持比例补边到 `640×360`
- 两端磁盘都很紧（约 2.5GB 可用），避免大体积复制

解码端不是 Git 仓库，同步方式仍然是 rsync 源码。

## 4. 当前运行状态

- 编码端网页：`http://127.0.0.1:7860`
- 解码端网页：`http://127.0.0.1:7861`
- 端口：`9860` DCVC 码流；H.264/H.265 的 `9861/9862` 已移除

先检查再操作：

```bash
ps -eo pid,etime,cmd | grep -E 'demo\.(app|receiver)' | grep -v grep
ss -ltnH | grep -E ':(7860|7861|9860)\b' || true
ssh jetson@192.168.50.2 "ps -eo pid,etime,cmd | grep -E 'demo\\.receiver' | grep -v grep"
```

## 5. 展示层（已完成）

改动集中在 `demo/web/`、`demo/app.py`、`demo/decoder_ui.py`：

- 编码端：左侧参数控制台 + 右侧全宽原始画面；影院模式隐藏侧栏；
- 解码端：全宽重建画面 + 显示健康度/处理速度面板；
- 画面支持全屏、放大弹层、滚轮缩放、拖动平移；
- 指标改为大数字卡片 + 90 秒滚动曲线 + 流水线分解 + 原始 JSON；
- H.264/H.265 面板、设置、后端进程和离线工具全部删除；
- 移动端无横向溢出。

## 6. 任务 3：显示流畅度（已完成）

### 根因

HT-S 一次产出 8 帧，旧代码用 `max(60, fps)` 的节奏播放：8 帧在 133ms 内闪完，然后空等约 130ms。浏览器实测只有 22–23fps，帧间隔 p95 约 163ms、最大曾到 411ms，这就是用户看到的“卡”。

### 修改

- `demo/decoder_ui.py`
  - 按采集节奏（30fps）出帧，不再 60fps 突发；
  - 到达时跳掉会超出显示预算的最旧帧，播放前再按 `CLOCK_MONOTONIC` 检查一次；
  - 显示预算 `DISPLAY_BUDGET_MS = 470`，为浏览器取帧/绘制留出余量；
  - 帧年龄用单调时钟累加，墙钟只在 `/api/frame/decoded` 出帧时换算一次。
- `demo/receiver.py`
  - 新增读 socket 线程，包一到就打时间戳，避免包在解码期间排队被少算；
  - 传输字段从“校准后的采集时间”改为 `capture_ages_ns`（发送时已过去的时长）。
- `demo/engine.py`
  - 跨机时钟每 3 秒重新校准；只接受 RTT < 5ms 的样本，1 秒内的真实阶跃会跟随；
  - 发送标记与数据包共用一把发送锁，保证回复顺序。

### 实测（解码端本机 Chromium，双机真实摄像头，75 秒 / 1800 个绘制样本）

| 指标 | 修改前 | 修改后 |
|---|---:|---:|
| 浏览器绘制 FPS | 23.6 | 28.8 |
| 帧到达间隔 p95 | 163 ms | 73 ms |
| 采集→canvas 中位数 | 461 ms | 463 ms |
| 采集→canvas p95 | 480 ms | 484 ms |
| 采集→canvas max | 514 ms | 590 ms（软件渲染尖峰） |

说明：

- 显示延迟比旧的“突发播放 + 丢过期帧”略高一点（中位数 461→463ms），因为现在整组帧按同一节奏播放，不再靠“后面的帧提前闪出”压低中位数；
- 帧间隔 p95 从 163ms 降到 73ms，用户感知的卡顿消失，这是本轮的核心收益；
- max 590ms 是 headless 软件渲染下的一次调度尖峰，p95 484ms 仍在 500ms 内；真实桌面 Chromium 需要按 `tests/browser_display_latency.py` 的 CDP 流程复测；
- 浏览器 FPS 仍比硬件低 2–5fps，代价是 470ms 预算下主动丢弃少量过期帧。

原始数据：[`reports/browser-display-smoothness-25w.json`](reports/browser-display-smoothness-25w.json)。

## 7. 论文与改进空间

已读 DCVC-UF 原论文（CVPR 2026, arXiv:2606.04410）并整理为 [`docs/paper-review.md`](docs/paper-review.md)。结论：

- 8 帧 chunk 是模型结构和 HT-S 权重的一部分（`g_frame_delay = 8`），不能改成 2/4 帧；
- 唯一能真正消掉 233ms 组等待的是官方 **LD（N=1）** 权重，代价是 BD-Rate 从 -31.6% 退到 -9.5%；
- 该权重不在本机（只有 image + HT-S），所以本轮没有接入，也没有改模型；
- 显示侧的收益已经拿完，继续压延迟必须换变体。

## 8. 已知问题与风险

### 8.1 跨机时钟漂移（已修复，仍有边界）

两块板子的墙钟会被 NTP 阶跃（实测几分钟内可跳 100–250ms）。现在：

- 帧年龄只由“编码端发送时的年龄 + 解码端本地单调时钟”计算，显示和预算不受墙钟阶跃影响；
- 校准只接受 RTT < 5ms 的样本，避免请求排在解码后面造成的偏置。

### 8.2 模型码率是窗口值

DCVC 在 QP32、当前摄像头场景下的实际码率只有约 2–3kbps（页面为最近 2 秒窗口；长稳平均约 2kbps）。这是模型载荷，不含预览和协议开销；不能把它当作复杂动态场景的代表值。

### 8.3 解码端不是 Git 仓库

继续用 rsync，保留解码端本地 `.env/`、`vendor/`、`checkpoints/`、`runs/`。

### 8.4 headless 模式没有展示页

`demo/receiver.py --headless` 仍不启动网页，属于预期行为。

### 8.5 延迟上限贴着 500ms

组等待 233ms + 编码约 97ms + 解码约 133ms + 预览约 10ms，本身就已经约 470ms。本轮把 p95 做到 463ms、max 482ms，但继续叠加负载（例如同时开浏览器调试）仍可能偶发超过 500ms。要留更大余量只能换 LD 变体。

## 9. 启动、停止与同步命令

### 启动

```bash
# 解码端先启动
cd ~/Desktop/dcvc-jetson-demo
./start_decoder.sh --no-browser

# 编码端再启动
cd ~/Desktop/dcvc-jetson-demo
./start_encoder.sh --no-browser
```

### 优雅停止采集

```bash
curl -fsS -X POST http://127.0.0.1:7860/api/control/stop \
  -H 'X-Demo-Request: 1'
```

退出服务：

```bash
curl -fsS -X POST http://127.0.0.1:7860/api/control/quit \
  -H 'X-Demo-Request: 1'

ssh jetson@192.168.50.2 'curl -fsS -X POST http://127.0.0.1:7861/api/control/quit \
  -H "X-Demo-Request: 1"'
```

远程重启解码端时，用 `ssh -T` + `setsid nohup ... < /dev/null &`，否则 SSH 会一直挂在后台进程的管道上。

### 同步到解码端

```bash
rsync -aR --exclude '__pycache__/' \
  demo tests tools/start_common.sh \
  docs README.md HANDOFF.md \
  launch.sh launch_decoder.sh receiver.sh start_encoder.sh start_decoder.sh \
  jetson@192.168.50.2:~/Desktop/dcvc-jetson-demo/

ssh jetson@192.168.50.2 \
  "cd ~/Desktop/dcvc-jetson-demo && \
   PYTHONPATH='' ./.env/bin/python -s -m compileall -q demo && \
   test -x .env/bin/python && test -d vendor/DCVC && echo remote-ok"
```

注意 `rsync -a demo/ dest/` 会把 `demo/*` 摊到目标根目录；要同步到 `demo/`，源和目标都写目录名。

## 10. 验证与提交要求

1. 全量测试：`PYTHONNOUSERSITE=1 PYTHONPATH='' ./.env/bin/python -s -m unittest discover -s tests -p 'test_*.py'`
2. `git diff --check`
3. 单独提交该任务
4. `git push origin main`
5. 同步解码端并重启两端验证

当前基线：**51 项通过**。项目没有安装 pytest，统一用 unittest。

最省事的双机验收：先启动两端，再开一个 Chromium 页面指向 `http://127.0.0.1:7861/`，读取 `/api/latency` 的 `summary`（浏览器回报的采集→canvas）。

## 11. 关键参考文件

- `README.md`
- `demo/web/`（自定义前端）
- `docs/paper-review.md`（DCVC-UF 论文要点与本项目改进评估）
- `docs/progress.md`
- `docs/dual-host-deployment.md`
- `reports/browser-display-smoothness-25w.json`
- `reports/browser-display-latency-25w.json`
- `tests/test_decoder_ui.py`
