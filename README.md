# Jetson DCVC Lab

两台 Jetson Orin NX 16GB 的 DCVC-UF HT-S 视频压缩演示。首期目标为 **640×360、30fps、端到端延迟 ≤500ms**；目标是否达标须以真实模型和双机测试为准。

## 打开软件

```bash
cd ~/Desktop/dcvc-jetson-demo
./launch.sh
```

脚本启动本地服务并打开浏览器 `http://127.0.0.1:7860`。打开页面不会自动采集。若未自动打开，手动访问该地址。也可运行 `./launch.sh --no-browser`。

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

需要两份权重。当前官方 OneDrive API 访问返回 401；若自动获取未成功，可在浏览器使用官方链接下载后放入该目录。请勿把其他变体的文件重命名为 HT-S。未提供权重时，界面仍可用于采集检查并显示缺失项。

```bash
./tools/build_codec.sh
PYTHONNOUSERSITE=1 PYTHONPATH="$PWD" .env/bin/python -s tools/benchmark.py --groups 20
```

构建默认并发 1，减少 16GB 内存压力。基准以 640×360 移动测试图案生成真实码流，排除 3 个预热组，保存墙钟编码/解码速度及实际字节数。它不代表真实摄像头内容的压缩效率，也不能替代双机验收。GPU 扩展是否成功请查看 `reports/build-cuda.log` 和项目进度文档。

## 第二台接入

当前第二台尚未接入，以下为接入步骤，尚未完成硬件验收：

1. 将项目源码、固定版本的 `vendor/DCVC` 和两份权重复制到第二台；使用 `environment.yml` 新建环境并安装相同 NVIDIA wheel、构建扩展。不要复制本机 `.env` 当作通用安装包。
2. 两台网线直接连接。有线网卡各设一个同网段静态地址，例如编码端 `192.168.50.1/24`、解码端 `192.168.50.2/24`。此网段应与现有 Wi-Fi 网段不同；有线连接不设置默认网关，保留 Wi-Fi 联网。程序不会自动修改系统网络。
3. 用 `ip -4 addr` 核对有线地址；两端通过有线地址互相 ping。
4. 在解码端运行：

   ```bash
   ./receiver.sh --bind 192.168.50.2 --port 9860
   ```

5. 编码端打开界面，选择“双机发送”，填写本机有线 IP `192.168.50.1` 和解码端 `192.168.50.2`。点击开始。程序检查路由并拒绝 Wi-Fi/回环路由。

接收端断开后会等待下一次连接；暂停/继续会创建新会话。每个接收会话使用独立进程，原生解码崩溃不会关闭监听服务；连续 180 秒没有解码进展会回收会话。初版 TCP 可靠传输和预览返回会占用额外时间；断线不自动恢复为旧参考状态，重新点击开始即可。接收服务仅绑定指定地址；请用于两机直连或可信实验网。

摄像头驱动若卡在底层读取调用，线程无法强制中断。程序会拒绝在旧采集线程仍存活时重新占用摄像头；这种情况需拔插摄像头或退出程序，真实 USB 稳定性仍待设备接入验证。

## 指标含义

- **采集 FPS**：实际获得的帧数；摄像头未必支持请求的采集模式，处理画面会保持比例缩放/补边。
- **编码/解码 FPS**：实际处理帧数除以墙钟时间，使用滚动 2 秒窗口，包含等待和停滞。
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

参考：[DCVC 官方仓库](https://github.com/microsoft/DCVC)、[NVIDIA Jetson PyTorch 安装说明](https://docs.nvidia.com/deeplearning/frameworks/install-pytorch-jetson-platform/index.html)、[用户提供的 Jetson 文档](https://github.com/MaxwellJay256/Jetson_Orin_NX_guide)、[Ponytail](https://github.com/dietrichgebert/ponytail)。
