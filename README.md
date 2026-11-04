# Jetson DCVC Lab

两台 Jetson Orin NX 16GB 的 DCVC-UF HT-S 视频压缩演示。首期目标为 **640×360、30fps、端到端延迟 ≤500ms**；目标是否达标须以真实模型和双机测试为准。

两台实机已通过网线连接，USB摄像头和解码端独立Miniforge环境均已部署；官方权重、原生扩展和真实HT-S码流已验证。56项自动化测试通过。解码端页面新增同一摄像头输入的 DCVC、H.264、H.265 三路实时画面及码率/时延指标。最新性能与限制见下方“实机结果”、[编解码器对比](docs/codec-comparison.md)及 `reports/browser-display-latency-25w.json`，部署详情见 [双机记录](docs/dual-host-deployment.md)。

## 一键启动（推荐）

开机后分别打开两台 Jetson 的终端，进入项目目录并运行对应入口。脚本会检查项目环境、25W 实际 CPU/GPU 限制和有线地址；地址缺失时会尝试启用已有的 `DCVC-Direct`/`DCVC-Decoder` 有线连接。服务已经运行时不会重复启动，只打开现有页面。

解码端先运行：

```bash
cd ~/Desktop/dcvc-jetson-demo
./start_decoder.sh
```

编码端再运行：

```bash
cd ~/Desktop/dcvc-jetson-demo
./start_encoder.sh
```

浏览器会分别打开 `http://127.0.0.1:7861` 和 `http://127.0.0.1:7860`。只检查环境、不启动服务可加 `--check`；无图形界面可加 `--no-browser`，解码端还支持 `--headless`。

## 手动启动与高级参数

```bash
cd ~/Desktop/dcvc-jetson-demo
./launch.sh
```

解码端先运行 `./launch_decoder.sh`，会打开本机 `http://127.0.0.1:7861`，等待连接并在第二台屏幕显示解码画面与实时速度。需要无界面接收时使用 `./receiver.sh --bind 192.168.50.2 --headless`。

编码端脚本启动本地服务并打开浏览器 `http://127.0.0.1:7860`。界面默认双机发送、USB摄像头及两端有线地址。打开页面不会自动采集。若未自动打开，手动访问该地址。也可运行 `./launch.sh --no-browser`。

若要从同一 Wi-Fi 的电脑集中操作，先用 `ip -4 addr` 查看编码端 Wi-Fi IP，再运行 `./launch.sh --host 编码端WiFi地址 --no-browser`，电脑访问 `http://编码端WiFi地址:7860`。此方式没有账号登录，只用于可信局域网。视频压缩码流仍绑定有线地址传输；浏览器预览和控制走 Wi-Fi。

- **仅检查采集 · 不压缩**：当前即可使用测试图案；插入摄像头后可切换 USB 摄像头。此模式不代表模型已工作。
- **本机编解码 · HT-S**：独立编码状态和解码状态，真实压缩码流；需要权重和两个扩展。
- **双机发送 · HT-S**：本机采集编码，码流通过网线发往另一台独立解码。接收端返回 JPEG 预览供浏览器展示；返回预览与模型压缩码流分别处理。

**开始**才启动采集。**暂停**停止采集和处理，保留最后画面；**继续**从当前时刻重新建立编解码状态。**结束**释放资源并保留统计。模型首次加载或 GPU 调用尚未返回时，需要等资源释放后再开始。**退出程序**关闭服务，浏览器标签页可以自行关闭。修改参数后点击**应用并重启**。

## 环境

项目独立 Miniforge 环境在 `.env`，Python 3.10，不需要修改系统 Python：

```bash
source ~/miniforge3/etc/profile.d/conda.sh
conda activate "$HOME/Desktop/dcvc-jetson-demo/.env"
```

也可直接调用 `.env/bin/python -s`。启动脚本已处理环境路径和隔离，不必手动激活。系统 Torch/CUDA 保持不变。

依赖见 `environment.yml` 和 `requirements-lock.txt`。PyTorch 使用 NVIDIA 官方适配 Jetson 的 aarch64 cp310 wheel（与本机已可用的版本一致），**不能简单换成通用 `pip install torch`**。JetPack/CUDA 不随 Python 环境一起替换。当前系统 CUDA 12.6、L4T R36.4.7、GPU SM87。两端尽量使用相同软件版本。

源码固定为 Microsoft DCVC `cbdae87a5445114cdc7f48816da63ea80bdeac40`，CUTLASS v4.4.1。原始代码放在 `vendor/DCVC`，编译兼容改动记录于 `patches/jetson-build.patch`。上游要求 Python ≥3.12；当前适配选择 3.10 以复用 NVIDIA 可用 wheel，已检查模型模块语法，实际支持范围仍以编译与运行结果为准。没有更改模型结构。

## 从 GitHub 克隆后重新部署

GitHub 仓库只保存源码、测试、文档和验证报告。以下内容体积过大或与设备相关，默认不进入 Git：

- `.env/`：项目 Conda 环境
- `vendor/`：Microsoft DCVC 上游源码、CUTLASS 和编译产物
- `checkpoints/`：官方模型权重
- `tools/testdata/`、`tools/*.whl`、`runs/` 和日志文件

在已安装 Miniforge、JetPack/CUDA 12.6 的 Jetson 上，克隆仓库后执行：

```bash
git clone git@github.com:pengjunjie04/DCVC.git
cd DCVC
./tools/bootstrap.sh
```

`tools/bootstrap.sh` 会依次：

1. 拉取固定提交的 DCVC 和 CUTLASS 到 `vendor/DCVC`；
2. 应用 `patches/jetson-build.patch`；
3. 从 `environment.yml` 创建项目 `.env`；
4. 安装 `requirements-lock.txt` 中的可移植依赖和官方 Jetson Torch；
5. 执行 `tools/build_codec.sh` 编译原生扩展。

如果已经创建 `.env`，只想拉取上游源码和补丁，可执行 `./tools/fetch_dcvc.sh`；不准备本轮编译时可运行 `./tools/bootstrap.sh --no-build`。脚本不会覆盖已有上游修改，发现不兼容状态会停止并提示。

Miniforge 不在默认位置时，通过 `CONDA_BIN=/path/to/conda ./tools/bootstrap.sh` 指定。`requirements-lock.txt` 不再包含本机绝对路径；原生扩展由构建脚本单独安装。

## 模型权重与构建

从 [Microsoft 官方仓库](https://github.com/microsoft/DCVC#readme) 的 Pretrained models 下载：

```text
checkpoints/cvpr2026_image.pth.tar
checkpoints/cvpr2026_video_hts.pth.tar
```

两份官方权重已下载并记录 SHA256，见 `reports/official-weight-downloads.json`。换设备时请一并复制，或从官方链接重新下载。请勿把其他变体的文件重命名为 HT-S。未提供权重时，界面仍可用于采集检查并显示缺失项。自动获取辅助脚本 `tools/fetch_weights_browser.py` 依赖 Playwright、系统 Chromium 和本机代理端口7897；无需在普通运行时使用。

下载或复制完成后运行：

```bash
PYTHONNOUSERSITE=1 .env/bin/python -s tools/check_weights.py
```

校验器会检查文件大小和 SHA256，避免误用其他 DCVC 变体。自动下载脚本可通过 `DCVC_CHROMIUM` 指定 Chromium 路径，通过 `DCVC_PROXY` 指定代理；不需要代理时设置 `DCVC_PROXY=''`。

```bash
./tools/build_codec.sh
PYTHONNOUSERSITE=1 PYTHONPATH="$PWD" .env/bin/python -s tools/benchmark.py --groups 20
```

构建默认并发 1，减少 16GB 内存压力。基准以 640×360 移动测试图案生成真实码流，排除 3 个预热组，保存墙钟编码/解码速度及实际字节数。它不代表真实摄像头内容的压缩效率，也不能替代双机验收。GPU 扩展是否成功请查看 `reports/build-cuda.log` 和项目进度文档。

与 Jetson 硬件 H.264/H.265 的同内容、同质量对比使用系统 Python：

```bash
python3 tools/compare_codecs.py --frames 640 --bitrates 32,64,128,256,512
```

计时边界、完整结果和局限见 [编解码器对比](docs/codec-comparison.md)。

### 实时同源对比

编码端页面勾选 **实时 H.264/H.265 对比** 后，同一帧图像会同时送入 DCVC-RT、NVENC H.264 和 NVENC H.265。两种硬件码流分别通过 `9861`/`9862` 端口发到解码端，由 NVDEC 解码为 JPEG；解码端页面因此可同时看到原始画面、DCVC 重建、H.264 重建和 H.265 重建，并显示硬件码率、吞吐及采集到解码完成的时延。码率滑块控制两路硬件编码器的目标码率，DCVC 仍由 QP 控制。

这一页用于实时观察画面和链路行为，**不是同质量 PSNR 对比**：DCVC 的 QP 与硬件编码器的目标 kbps 不是同一个质量尺度。等质量码率结论仍以离线测试和 [编解码器对比](docs/codec-comparison.md) 为准，模型结构与延迟取舍见 [DCVC-UF 论文要点](docs/paper-review.md)。实时指标也不包含浏览器绘制、摄像头曝光和屏幕扫描。

2026-11-04 在两端 25W、真实 USB 摄像头下连续采样 15 秒（640×360/30fps/QP32、硬件目标 300kbps）：H.264/H.265 编码端实测约 298.5/300.4kbps、30.05/30.09fps，编码端采集到编码完成中位数 12.3/13.4ms；解码端硬件吞吐约 30.21/30.18fps，采集到 NVDEC 生成 JPEG 的中位数 4.6/5.4ms。两条连接全程正常，页面 DCVC 预览约 30.5fps、采集→canvas 中位数 465.7ms、p95 481.0ms。这里的硬件时延含跨机时钟校准，且与 DCVC 的显示口径不同，不应直接当作同质量画质结论。原始统计见 `reports/realtime-hardware-comparison-25w.json`。

## 第二台接入

本次两台设备已完成部署：编码端192.168.50.1、解码端192.168.50.2。解码端可直接从第4步启动接收服务；第1–3步供重新部署参考：

1. 在第二台克隆仓库并准备固定版本上游源码。不要复制本机 `.env` 当作通用安装包。第二台安装 Miniforge 后，若也是相同 JetPack/CUDA12.6，在项目目录运行：

   ```bash
   git clone git@github.com:pengjunjie04/DCVC.git
   cd DCVC
   ./tools/bootstrap.sh
   ```

   两份官方权重仍需按下一节说明放入 `checkpoints/`。若系统/CUDA 版本不同，先匹配环境，避免直接覆盖系统组件。
2. 两台网线直接连接。有线网卡各设一个同网段静态地址，例如编码端 `192.168.50.1/24`、解码端 `192.168.50.2/24`。此网段应与现有 Wi-Fi 网段不同；有线连接不设置默认网关，保留 Wi-Fi 联网。程序不会自动修改系统网络。
3. 用 `ip -4 addr` 核对有线地址；两端通过有线地址互相 ping。
4. 在解码端运行：

   ```bash
   ./launch_decoder.sh --port 9860
   ```

5. 编码端打开界面，选择“双机发送”，填写本机有线 IP `192.168.50.1` 和解码端 `192.168.50.2`。点击开始。程序检查路由并拒绝 Wi-Fi/回环路由。

接收端断开后会等待下一次连接；暂停/继续会创建新会话。每个接收会话使用独立进程，原生解码崩溃不会关闭监听服务；连续 180 秒没有解码进展会回收会话。初版 TCP 可靠传输和预览返回会占用额外时间；断线不自动恢复为旧参考状态，重新点击开始即可。接收服务仅绑定指定地址；请用于两机直连或可信实验网。

USB 摄像头路径显式请求未压缩 YUYV：先设置格式，再请求 640×480@30，并读回格式、尺寸和帧率校验；原始画面保持比例补边到模型输入（默认 640×360）。驱动若只返回 MJPG、或无法达到请求模式，程序立即报错，不会静默回退到 JPEG 传输。实测协商为 YUYV 640×480@30、引擎输出 640×360，统计见 `reports/camera-yuyv-640x480-30fps.json`。

摄像头驱动若卡在底层读取调用，线程无法强制中断。程序会拒绝在旧采集线程仍存活时重新占用摄像头；这种情况需拔插摄像头或退出程序，当前摄像头已通过双机短时运行，长时间及拔插稳定性仍需另测。

## 画质与运行库

两端cuDNN版本不同曾造成跨帧画质持续劣化，现已通过项目私有运行库统一为9.20，系统环境保持不变。257帧公开视频回归通过；启动后首帧会检查两端推理环境，版本不同则拒绝解码。复现、测试口径和部署位置见 [画质一致性记录](docs/quality-consistency.md)。QP越大通常质量和码率越高；该模型的QP方向不同于常见传统编码器。

## 指标含义

- **采集 FPS**：实际获得的帧数；USB 摄像头要求显式 YUYV 模式，驱动回退 MJPG 或无法满足格式/尺寸/帧率时直接报错，处理画面会保持比例缩放/补边。
- **编码/解码 FPS**：实际处理帧数除以墙钟时间，使用滚动 2 秒窗口，包含等待和停滞。
- **编码/解码处理速度**：编解码方法内的实际处理帧数÷耗时，同时显示ms/帧；排除采集等待和网络。计时范围比论文核心模型更宽，详细说明见 [速度对照](docs/metrics-comparison.md)。
- **画面角落 FPS**：浏览器完成图像解码和 canvas 绘制后的计数，不用目标 FPS 或后端推送次数代替。
- **压缩 Mbps**：模型实际码流载荷的在线吞吐，**不包含**分包头、原始预览或返回 JPEG 预览；不是总网卡流量，也不是承诺的恒定码率。初版 QP 调节，尚无目标 Mbps 自动控制。
- **丢帧**：分别统计尚未编码的采集帧和展示队列丢帧。已编码的 P 帧不随意丢弃。
- **延迟**：本机模式统计采集至解码完成；双机模式统计采集至收到返回预览的往返耗时。解码页把同一组 8 帧按采集节奏（30fps）播放，而不是一次闪出；超过 500ms 显示预算的帧会被跳过并计入展示丢帧，因此显示年龄始终有界。跨机时钟每 3 秒用低 RTT 样本重新校准，硬件时延不会因为时钟漂移变成负数。第二台页面另显示“采集完成→canvas drawImage 完成”的软件时延：帧年龄由编码端单调时钟在发送时测得、解码端用本地单调时钟累加，再换算成绘制时刻的年龄，因此不依赖两机墙钟一致；口径包含 JPEG 预览 IPC 与浏览器绘制，不包含摄像头曝光和物理屏幕扫描。为避免显示过期画面，服务器端先按显示预算跳帧，浏览器再对超过 495ms 的帧做最后一道丢弃。
- **H.264/H.265 实时指标**：码率为对应 NVENC 实际发送载荷；端到端为采集时间到本机 NVDEC 解码并生成 JPEG 的时间，不含浏览器绘制；吞吐为最近 2 秒实际解码帧率。它们与 DCVC 的 500ms 显示口径分开显示，不能直接混用。

HT-S 每组 8 帧，30fps 时组内首帧等待其余帧约 233ms，另加编码、传输、解码和展示时间。

统计报告保存于 `runs/`，默认不保存摄像头画面或压缩码流。

## 验证与文件结构

```bash
PYTHONNOUSERSITE=1 PYTHONPATH='' .env/bin/python -s -m unittest discover -s tests -v
# 界面已启动时，使用系统 Chromium 做浏览器操作验证：
PYTHONNOUSERSITE=1 PYTHONPATH='' .env/bin/python -s tests/browser_smoke.py
```

`demo/codec.py` 封装上游模型；`engine.py` 管理采集、处理和预览线程；`transport.py` 处理有线数据；`receiver.py` 是独立解码入口；`app.py` 是 Gradio 界面。`docs/requirements.md` 保存确认需求，`docs/progress.md` 保存进度和限制，`reports/` 保存检查及测试证据。

`tools/check_restart.py` 使用正式模型检查三轮启停和 GPU 张量回收；`tools/smoke_independent_processes.py --pretrained` 先编码并退出，再在全新进程解码真实码流，适合在单台16GB设备上验证状态独立性。同一台设备同时启动两个独立 CUDA 进程曾出现内存不足，因此本机编解码采用单进程两组模型状态，双机仍各自独立运行。

另用 [OpenCV 官方示例 vtest.avi](https://github.com/opencv/opencv/blob/master/samples/data/vtest.avi) 的行人场景完成纹理更复杂的补充测试：QP32、160个计量帧、640×360缩放补边，编码约148fps、解码约130fps，见 `reports/natural-clip-benchmark.json`。原片为10fps，未改写为摄像头30fps的验收结果；文件读取不计入编码耗时。可用 `tools/benchmark.py --input-video 文件路径 --output reports/自定义报告.json` 复现。

论文与改进评估：[DCVC-UF 论文要点](docs/paper-review.md)。

参考：[DCVC 官方仓库](https://github.com/microsoft/DCVC)、[NVIDIA Jetson PyTorch 安装说明](https://docs.nvidia.com/deeplearning/frameworks/install-pytorch-jetson-platform/index.html)、[用户提供的 Jetson 文档](https://github.com/MaxwellJay256/Jetson_Orin_NX_guide)、[Ponytail](https://github.com/dietrichgebert/ponytail)。

## 实机结果

640×360、30fps、QP32，真实USB摄像头→本机编码→有线TCP→第二台解码→返回JPEG→Gradio浏览器。编码、远端解码和预览采用有界流水线。摄像头原生640×480 YUYV30，保持比例补边到640×360。

修复启动顺序和跨机运行库不一致后，两端实际25W下复测：约69秒稳态内采集29.98fps、编码/解码29.99fps，第二台实际桌面Chromium绘制中位数29.9fps；稳态采集、返回预览和解码端展示丢帧均为0，两端OC计数均为0。编码/解码处理速度中位数50.37/47.74fps，计时包含转换与拷贝。开始、暂停、继续后实际解码新帧、结束及导出通过。报告为 `reports/dual-display-camera-browser-quality-fixed.json`，最近报告同步于 `reports/dual-host-camera-browser.json`。

画质单独以257帧公开片段回归：QP32下末组RGB PSNR31.34dB、最差单帧30.48dB（包含JPEG75），无此前持续劣化；不记录摄像头画面，也不把公开视频的PSNR当作摄像头场景的质量分数。详情见 [画质一致性记录](docs/quality-consistency.md)。旧环境的出帧/速度报告不能独立证明画质正确。

2026-11-04 显示流畅度专项：解码页仍按 8 帧一组接收，但改为按采集节奏（30fps）播放，并在到达与播放前各做一次 500ms 预算检查，超过预算的最旧帧会被丢弃。帧年龄由“编码端发送时已经过去多久”加“解码端本地单调时钟”计算，因此两块板子的 NTP 阶跃不会再把旧帧算成新帧；跨机校准每 3 秒重做一次。解码端本机 Chromium 实测（640×360/30fps/QP32、硬件 300kbps、75 秒）：浏览器绘制 28.8fps（原 23.6fps），帧间隔 p95 从 163ms 降到 73ms，采集→canvas 中位数 463.4ms、p95 484.2ms、max 590ms（软件渲染调度尖峰）。代价是显示中位数比旧的突发播放略高，且 DCVC 帧率仍比硬件低约 2–5fps。证据见 `reports/browser-display-smoothness-25w.json`。

2026-11-03 低延迟优化后，同样两端25W、640×360/30fps/QP32的真实摄像头复测：40个连续稳态样本中，组内最老帧到编码端收到返回预览的中位数478.9ms、最大490.8ms，**该返回预览口径已低于500ms**；同组最新帧中位数245.3ms。典型分解为组帧等待234.1ms、编码98.8ms、远端解码133.3ms；稳态采集丢帧增量为0，两端OC计数仍为0。报告见 `reports/dual-host-latency-25w.json`。这个结果不包含浏览器绘制和摄像头曝光。

随后在第二台实际桌面 Chromium 完成 40 秒完整显示口径验收：跨机时钟偏移约-14.7ms、RTT约0.71ms；1049个实际绘制样本的中位时延425.8ms、p95 475.2ms、最大479.8ms，采集→canvas软件时延低于500ms。模型编码/解码仍约30fps，浏览器实际绘制约24.3fps；为控制延迟，显示端丢弃247个过期帧。编码端采集丢帧增量4，两端OC计数均为0。报告见 `reports/browser-display-latency-25w.json`。该口径不含摄像头曝光和物理屏幕扫描，不是glass-to-glass测量。

同内容离线对比中，DCVC-RT QP32 在 640 帧公开视频上为 32.99dB、42.7kbps；匹配该 PSNR 的 H.264/H.265 实测码率约为322.2/328.2kbps。DCVC处理速度约90.7/67.1fps，硬件编解码器约900–1100/575–730fps。该结果说明低码率优势和处理余量，不是网络延迟或摄像头场景质量结论，详见 [编解码器对比](docs/codec-comparison.md)。

当前实际场景的模型码率很低，不能据此代表复杂动态场景。返回预览和采集→canvas两个软件口径均已验收，但摄像头曝光、屏幕扫描和不同动态场景仍需单独测量。
