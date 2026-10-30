# Jetson DCVC Lab

两台 Jetson Orin NX 16GB 的 DCVC-UF HT-S 视频压缩演示。首期目标为 **640×360、30fps、端到端延迟 ≤500ms**；目标是否达标须以真实模型和双机测试为准。

两台实机已通过网线连接，USB摄像头和解码端独立Miniforge环境均已部署；官方权重、原生扩展和真实HT-S码流已验证。39项自动化测试通过。最新性能与限制见下方“实机结果”及 `reports/dual-host-camera-browser.json`，部署详情见 [双机记录](docs/dual-host-deployment.md)。

## 打开软件

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

## 模型权重与构建

从 [Microsoft 官方仓库](https://github.com/microsoft/DCVC#readme) 的 Pretrained models 下载：

```text
checkpoints/cvpr2026_image.pth.tar
checkpoints/cvpr2026_video_hts.pth.tar
```

两份官方权重已下载并记录 SHA256，见 `reports/official-weight-downloads.json`。换设备时请一并复制，或从官方链接重新下载。请勿把其他变体的文件重命名为 HT-S。未提供权重时，界面仍可用于采集检查并显示缺失项。自动获取辅助脚本 `tools/fetch_weights_browser.py` 依赖 Playwright、系统 Chromium 和本机代理端口7897；无需在普通运行时使用。

```bash
./tools/build_codec.sh
PYTHONNOUSERSITE=1 PYTHONPATH="$PWD" .env/bin/python -s tools/benchmark.py --groups 20
```

构建默认并发 1，减少 16GB 内存压力。基准以 640×360 移动测试图案生成真实码流，排除 3 个预热组，保存墙钟编码/解码速度及实际字节数。它不代表真实摄像头内容的压缩效率，也不能替代双机验收。GPU 扩展是否成功请查看 `reports/build-cuda.log` 和项目进度文档。

## 第二台接入

本次两台设备已完成部署：编码端192.168.50.1、解码端192.168.50.2。解码端可直接从第4步启动接收服务；第1–3步供重新部署参考：

1. 将项目源码、固定版本的 `vendor/DCVC`（包含 CUTLASS）和两份权重复制到第二台。不要复制本机 `.env` 当作通用安装包。第二台安装 Miniforge 后，若也是相同 JetPack/CUDA12.6，在项目目录运行：

   ```bash
   ~/miniforge3/bin/conda env create -p ./.env -f environment.yml
   PYTHONNOUSERSITE=1 PYTHONPATH='' .env/bin/python -s -m pip install \
     'https://developer.download.nvidia.com/compute/redist/jp/v61/pytorch/torch-2.5.0a0+872d972e41.nv24.08.17622132-cp310-cp310-linux_aarch64.whl'
   ./tools/build_codec.sh
   ```

   若系统/CUDA 版本不同，先匹配环境，避免直接覆盖系统组件。
2. 两台网线直接连接。有线网卡各设一个同网段静态地址，例如编码端 `192.168.50.1/24`、解码端 `192.168.50.2/24`。此网段应与现有 Wi-Fi 网段不同；有线连接不设置默认网关，保留 Wi-Fi 联网。程序不会自动修改系统网络。
3. 用 `ip -4 addr` 核对有线地址；两端通过有线地址互相 ping。
4. 在解码端运行：

   ```bash
   ./launch_decoder.sh --port 9860
   ```

5. 编码端打开界面，选择“双机发送”，填写本机有线 IP `192.168.50.1` 和解码端 `192.168.50.2`。点击开始。程序检查路由并拒绝 Wi-Fi/回环路由。

接收端断开后会等待下一次连接；暂停/继续会创建新会话。每个接收会话使用独立进程，原生解码崩溃不会关闭监听服务；连续 180 秒没有解码进展会回收会话。初版 TCP 可靠传输和预览返回会占用额外时间；断线不自动恢复为旧参考状态，重新点击开始即可。接收服务仅绑定指定地址；请用于两机直连或可信实验网。

摄像头驱动若卡在底层读取调用，线程无法强制中断。程序会拒绝在旧采集线程仍存活时重新占用摄像头；这种情况需拔插摄像头或退出程序，当前摄像头已通过双机短时运行，长时间及拔插稳定性仍需另测。

## 画质与运行库

两端cuDNN版本不同曾造成跨帧画质持续劣化，现已通过项目私有运行库统一为9.20，系统环境保持不变。257帧公开视频回归通过；启动后首帧会检查两端推理环境，版本不同则拒绝解码。复现、测试口径和部署位置见 [画质一致性记录](docs/quality-consistency.md)。QP越大通常质量和码率越高；该模型的QP方向不同于常见传统编码器。

## 指标含义

- **采集 FPS**：实际获得的帧数；摄像头未必支持请求的采集模式，处理画面会保持比例缩放/补边。
- **编码/解码 FPS**：实际处理帧数除以墙钟时间，使用滚动 2 秒窗口，包含等待和停滞。
- **编码/解码处理速度**：编解码方法内的实际处理帧数÷耗时，同时显示ms/帧；排除采集等待和网络。计时范围比论文核心模型更宽，详细说明见 [速度对照](docs/metrics-comparison.md)。
- **画面角落 FPS**：浏览器完成图像解码和 canvas 绘制后的计数，不用目标 FPS 或后端推送次数代替。
- **压缩 Mbps**：模型实际码流载荷的在线吞吐，**不包含**分包头、原始预览或返回 JPEG 预览；不是总网卡流量，也不是承诺的恒定码率。初版 QP 调节，尚无目标 Mbps 自动控制。
- **丢帧**：分别统计尚未编码的采集帧和展示队列丢帧。已编码的 P 帧不随意丢弃。
- **延迟**：本机模式统计采集至解码完成；双机模式统计采集至收到返回预览的往返耗时，**不等同于单向端到端或浏览器显示延迟**。正式 ≤500ms 验收建议用摄像头拍摄计时器并与浏览器显示同屏记录，或加入经过校准的跨机时钟同步与显示回执。

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

参考：[DCVC 官方仓库](https://github.com/microsoft/DCVC)、[NVIDIA Jetson PyTorch 安装说明](https://docs.nvidia.com/deeplearning/frameworks/install-pytorch-jetson-platform/index.html)、[用户提供的 Jetson 文档](https://github.com/MaxwellJay256/Jetson_Orin_NX_guide)、[Ponytail](https://github.com/dietrichgebert/ponytail)。

## 实机结果

640×360、30fps、QP32，真实USB摄像头→本机编码→有线TCP→第二台解码→返回JPEG→Gradio浏览器。编码、远端解码和预览采用有界流水线。摄像头原生640×480 YUYV30，保持比例补边到640×360。

修复启动顺序和跨机运行库不一致后，两端实际25W下复测：约69秒稳态内采集29.98fps、编码/解码29.99fps，第二台实际桌面Chromium绘制中位数29.9fps；稳态采集、返回预览和解码端展示丢帧均为0，两端OC计数均为0。编码/解码处理速度中位数50.37/47.74fps，计时包含转换与拷贝。开始、暂停、继续后实际解码新帧、结束及导出通过。报告为 `reports/dual-display-camera-browser-quality-fixed.json`，最近报告同步于 `reports/dual-host-camera-browser.json`。

画质单独以257帧公开片段回归：QP32下末组RGB PSNR31.34dB、最差单帧30.48dB（包含JPEG75），无此前持续劣化；不记录摄像头画面，也不把公开视频的PSNR当作摄像头场景的质量分数。详情见 [画质一致性记录](docs/quality-consistency.md)。旧环境的出帧/速度报告不能独立证明画质正确。

采集到收到返回预览时延中位数604.0ms、采样最大709.6ms，**≤500ms仍未达标**，完整屏幕显示时延未测。稳态计量排除首次模型加载和GPU预热，初始化期间仍会丢弃尚未编码的过期采集帧。较早MAXN及25W未完整生效的报告保留用于追溯，不能作为当前结果。

当前实际场景的模型码率很低，不能据此代表复杂动态场景。30fps吞吐与≤500ms完整显示时延须分别验收；采集到返回预览的时延不包含浏览器绘制和摄像头内部延迟。
