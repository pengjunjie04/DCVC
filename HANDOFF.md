# DCVC Jetson 项目交接说明

更新时间：2026-11-04 17:30（Asia/Shanghai）

## 1. 用户目标

当前线程的目标是三项，每完成一项都要单独提交并同步两台 Jetson：

1. 增加与 H.264、H.265 的实时对比。
2. 把浏览器展示页面做得更美观。
3. 进一步提升显示流畅度。

用户要求中文、直接、尽量简洁；安全第一。不要删除 `.env/`、`vendor/`、`checkpoints/`、`runs/`，不要用 `rm -rf`。停止进程优先 `kill -TERM`，只有无响应时才考虑强制终止。

## 2. 当前 Git 状态

- 仓库：`/home/jetson/Desktop/dcvc-jetson-demo`
- 分支：`main`
- 远端：`git@github.com:pengjunjie04/DCVC.git`
- 最新提交：`6f1f904 Add real-time H.264 and H.265 comparison`
- 该提交已推送到 `origin/main`
- 任务 1 已完成；任务 2、3 尚未开始

交接前工作区是干净的；本文件随后会单独提交。

## 3. 双机与环境

- 编码端：`192.168.50.1`，主机名 `yahboom`
- 解码端：`192.168.50.2`，SSH 用户 `jetson`
- 两端均为 25W 模式，Jetson Orin NX 16GB
- 项目环境：`.env/`，项目 Python 为 `.env/bin/python`
- GStreamer/NVENC/NVDEC 工作进程必须使用系统 Python：`/usr/bin/python3`
- 摄像头：编码端 `/dev/video0`，实测 `YUYV 640×480@30`，程序保持比例补边到 `640×360`
- 编码端磁盘约 2.5GB 可用，解码端约 2.7GB 可用，避免任何大体积复制

解码端不是 Git 仓库。此前和当前采用的同步方式是 rsync 源码，不能假设解码端可以直接 `git pull`。

## 4. 当前运行状态（交接时）

采集会话已通过 API 优雅停止，**两端网页服务仍在运行**，浏览器打开后点击“开始”即可再次采集。

- 编码端网页：`http://127.0.0.1:7860`
- 解码端网页：`http://127.0.0.1:7861`
- 编码端进程：`demo.app` PID `55497`
- 解码端进程：`demo.receiver` PID `22369`
- 解码端硬件接收进程：`hw_stream_worker.py decoder` PID `22686`
- 编码端硬件工作进程已随采集停止退出

这些 PID 只是交接时的快照，下一位 agent 应先重新检查，不要盲杀：

```bash
ps -eo pid,etime,cmd | grep -E 'demo\.(app|receiver)|hw_stream_worker' | grep -v grep
ss -ltnH | grep -E ':(7860|7861|9860|9861|9862)\b' || true
ssh jetson@192.168.50.2 "ps -eo pid,etime,cmd | grep -E 'demo\\.receiver|hw_stream_worker' | grep -v grep"
```

端口约定：

- `7860`：编码端网页/API
- `7861`：解码端网页/API，只绑定解码端 `127.0.0.1`
- `9860`：DCVC 码流
- `9861`：H.264 硬件码流
- `9862`：H.265 硬件码流

## 5. 任务 1：实时 H.264/H.265 对比（已完成）

### 实现结构

- `demo/engine.py`：采集线程把同一 RGB 帧同时送入 DCVC 和 `HardwareEncoder`。
- `demo/hardware_compare.py`：父进程管理硬件工作进程、统计和共享 JPEG 帧。
- `tools/hw_stream_worker.py`：系统 Python + GStreamer，负责 NVENC 编码、TCP 发送、NVDEC 解码和 JPEG 生成。
- `demo/receiver.py`：解码端启动硬件接收进程。
- `demo/decoder_ui.py`：解码页提供 `/api/frame/h264`、`/api/frame/h265` 和硬件统计。
- `demo/preview.js`：解码页轮询原始、DCVC、H.264、H.265 四路画面。
- `demo/ui_parts.py`、`demo/style.css`：增加第 03/04 两路视频面板。

硬件编码链路：

```text
同一 RGB 帧
  ├─ DCVC-RT ── TCP 9860 ──→ 解码端 DCVC
  ├─ NVENC H.264 ─ TCP 9861 ─→ NVDEC → JPEG → /dev/shm/dcvc-hw-h264.frame
  └─ NVENC H.265 ─ TCP 9862 ─→ NVDEC → JPEG → /dev/shm/dcvc-hw-h265.frame
```

关键修复：

- NVDEC 管线加入 `disable-dpb=true`，消除 H.264 旧帧滞留。
- 编码端输入协议同时携带“本地采集时间”和“跨机校准采集时间”，避免时钟偏移把 NVENC 本机耗时截成 0。
- 解码端不再硬编码 30fps，而是使用码流元数据中的实际 fps 生成 PTS。

### 已验证结果

- 全量 `unittest`：54 项通过。
- 本机回环 NVENC→TCP→NVDEC：两路均产生有效 JPEG。
- 双机真实 USB 摄像头 15 秒采样：H.264/H.265 编码约 `30.05/30.09fps`，解码约 `30.21/30.18fps`；目标 300kbps 时实际约 `298.5/300.4kbps`；编码端时延中位数约 `12.3/13.4ms`，解码统计时延约 `4.6/5.4ms`。
- 同一时间 DCVC 预览约 `30.5fps`，采集→canvas 中位数约 `465.7ms`、p95 `481.0ms`。
- 原始证据：`reports/realtime-hardware-comparison-25w.json`。

重要口径：实时硬件指标**不是 PSNR 等质量对比**。DCVC 的 QP 和硬件编码器的目标 kbps 不是同一质量尺度。离线同质量结论仍在 `docs/codec-comparison.md`。

## 6. 任务 2：页面美化（未开始）

当前页面是 Gradio + 自定义 HTML/CSS。相关文件：

- `demo/app.py`
- `demo/decoder_ui.py`
- `demo/ui_parts.py`
- `demo/style.css`
- `demo/preview.js`

建议做法：

- 先启动两端服务，用实际 Chromium 截图检查编码页和解码页，而不是只看代码。
- 重点整理四路画面的层级、间距、卡片一致性、指标可读性和移动/窄屏布局。
- 保持现有功能、API 和统计口径不变；避免为了视觉效果引入大型前端依赖。
- 修改后运行全量测试和浏览器 smoke，再做双机真实页面检查。
- 完成后单独提交，例如 `Polish the browser dashboard`，并同步解码端。

现有测试和辅助：

```bash
PYTHONNOUSERSITE=1 PYTHONPATH='' ./.env/bin/python -s -m unittest discover -s tests -p 'test_*.py' -v
PYTHONNOUSERSITE=1 PYTHONPATH='' ./.env/bin/python -s tests/browser_smoke.py
```

## 7. 任务 3：提升显示流畅度（未开始）

已知事实（交接前最后一次活动的状态）：

- DCVC 模型编码/解码吞吐约 30–32fps。
- 解码页预览吞吐约 31.5fps。
- 采集→canvas 中位数约 `461ms`、p95 `480ms`、最大曾到 `547ms`。
- `batch_wait_ms` 约 `232ms`，来自 HT-S 每组 8 帧的组批等待。
- 长时间运行时解码端会累积展示丢帧；用户此前实际看到过约 `12–13fps` 的浏览器绘制，需要重新以浏览器实测为准，不能只看后端预览 FPS。
- 最新停止前的活动状态曾出现 `encode_group_ms≈189ms`、`decode_group_ms≈187ms`，说明硬件对比并行运行时 GPU 竞争会增加 DCVC 组耗时。

建议先做测量再改代码：

1. 用实际桌面 Chromium 和现有 `/api/state`、`/api/latency`、`/api/preview/drawn` 统计浏览器绘制 FPS、中位数/p95、展示丢帧。
2. 确认四路硬件预览是否增加编码端/解码端 GPU 和 CPU 压力。
3. 评估把 8 帧组批改成 2/4 帧是否可行；必须先验证模型语义、码流、画质、延迟和吞吐，不能只改 batch 等待时间。
4. 检查浏览器 JPEG 解码和 canvas 绘制路径，以及过期帧丢弃逻辑。
5. 保持 DCVC 码流兼容和现有测试通过，然后做双机真实摄像头验收。
6. 完成后单独提交，例如 `Improve browser display smoothness`，并同步解码端。

## 8. 已知问题与风险（下一位 agent 优先阅读）

### 8.1 跨机时钟漂移导致硬件时延可能变负

交接时连续运行约 5 分钟后，解码端 H.264/H.265 的 `latency_ms` 从正数变成了约 `-42ms`。原因很可能是：跨机时钟偏移只在会话开始时通过 NTP 式校准一次，随后两块板卡的时钟继续漂移；而硬件解码时延使用“解码端当前时间 - 编码端校准后的采集时间”计算。

这会同时影响：

- 解码端 H.264/H.265 的端到端时延显示；
- 现有 DCVC 的 `capture_to_canvas` 口径也可能受同类漂移影响。

建议修复方向（选一种并验证）：

1. 会话运行期间每隔 30–60 秒重新做 NTP 式时钟校准，并把最新偏移用于新帧。
2. 单独显示“解码端本地 NVDEC→JPEG 耗时”，不要把它伪装成跨机端到端时延；网络时延另列。
3. 对负时延做显式异常检测，而不是在 UI 上显示负数。

修改后要重新跑双机长时间测试，至少覆盖数分钟，不能只用 15 秒样本。

### 8.2 实时对比不是等质量比较

不要把实时 H.264/H.265 与 DCVC 的码率差异解释成压缩效率差异。实时页只用于同源画面和链路观察；PSNR/等质量结论必须使用离线 `tools/compare_codecs.py` 和 `docs/codec-comparison.md`。

### 8.3 解码端不是 Git 仓库

不要假设 `git pull` 可用。同步源码时要保留解码端本地的 `.env/`、`vendor/`、`checkpoints/`、`runs/`。

### 8.4 headless 模式没有硬件对比页

`demo/receiver.py` 在 `--headless` 时不启动网页，也不启动 `HardwareDecoder`。这是当前预期行为；如果后续要求无界面记录硬件指标，需要另行设计。

### 8.5 编码页没有 H.264/H.265 画布

编码页仍只有原始/DCVC 两路画面；H.264/H.265 对比画面只在解码页。`preview.js` 在编码页会请求不存在的硬件画面端点，但错误被静默忽略，不影响功能。若页面美化时想统一，可显式只在解码页启动这两个轮询。

## 9. 启动、停止与同步命令

### 启动（服务尚未运行时）

推荐一键入口：

```bash
# 解码端先启动
cd ~/Desktop/dcvc-jetson-demo
./start_decoder.sh --no-browser

# 编码端再启动
cd ~/Desktop/dcvc-jetson-demo
./start_encoder.sh --no-browser
```

当前两端网页服务已在运行，只需在浏览器打开：

- 编码端：`http://127.0.0.1:7860`
- 解码端：`http://127.0.0.1:7861`

### 优雅停止采集

```bash
curl -fsS -X POST http://127.0.0.1:7860/api/control/stop \
  -H 'X-Demo-Request: 1'
```

如需退出服务，再发送：

```bash
curl -fsS -X POST http://127.0.0.1:7860/api/control/quit \
  -H 'X-Demo-Request: 1'

ssh jetson@192.168.50.2 'curl -fsS -X POST http://127.0.0.1:7861/api/control/quit \
  -H "X-Demo-Request: 1"'
```

必要时才用 `kill -TERM <PID>` 结束残留主进程。

### 同步到解码端

只同步源码和脚本，不做删除：

```bash
rsync -aR --exclude '__pycache__/' \
  demo tests tools/hw_stream_worker.py tools/start_common.sh \
  docs README.md HANDOFF.md \
  launch.sh launch_decoder.sh receiver.sh start_encoder.sh start_decoder.sh \
  jetson@192.168.50.2:~/Desktop/dcvc-jetson-demo/
```

同步后检查：

```bash
ssh jetson@192.168.50.2 \
  "cd ~/Desktop/dcvc-jetson-demo && \
   PYTHONPATH='' ./.env/bin/python -s -m compileall -q demo tools/hw_stream_worker.py && \
   test -x .env/bin/python && test -d vendor/DCVC && echo remote-ok"
```

## 10. 验证与提交要求

每个任务完成后都必须：

1. 运行全量测试；必要时补浏览器和双机真实验收。
2. `git diff --check`。
3. 单独提交该任务，不要混入下一项。
4. `git push origin main`。
5. 同步解码端源码并重启两端验证。

测试命令：

```bash
PYTHONNOUSERSITE=1 PYTHONPATH='' ./.env/bin/python -s -m unittest discover -s tests -p 'test_*.py' -v
```

项目没有安装 `pytest`，使用 `unittest`。当前基线为 54 项通过。

## 11. 关键参考文件

- `README.md`
- `docs/codec-comparison.md`
- `docs/progress.md`
- `docs/dual-host-deployment.md`
- `reports/realtime-hardware-comparison-25w.json`
- `reports/browser-display-latency-25w.json`
- `tests/test_hardware_compare.py`
- `tests/test_decoder_ui.py`

