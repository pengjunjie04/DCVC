# 双机实机部署记录（2026-10-30）

两端项目均在 `~/Desktop/dcvc-jetson-demo`。编码端有线地址192.168.50.1/24；解码端jetson@yahboom，有线地址192.168.50.2/24。物理千兆链路，未配置有线默认网关，Wi-Fi继续承担上网与管理。

## 已验证的环境

两端均为Orin NX16GB、CUDA12.6、SM87，使用独立Miniforge和项目`.env` Python3.10、NVIDIA Torch2.5.0a0+872d972e41.nv24.08。没有替换系统Torch/CUDA，也没有修改解码端原有Miniconda环境或其他DCVC目录。

编码端L4T R36.4.7、系统cuDNN9.20.0；解码端R36.4.3、系统cuDNN9.6.0。原先仅检查出帧及速度遗漏了画质漂移。现已在解码端项目私有目录部署同版cuDNN9.20.0，两个启动器按项目设置加载，未替换系统库；首I帧会拒绝不一致的推理环境。257帧公开片段画质回归通过，详情见 [画质记录](quality-consistency.md)。

解码端安装了新的`~/miniforge3`，使用明确的conda包清单新建`.env`，再离线安装匹配的Python wheels。未直接搬移编码端的整个环境。两项原生扩展在确认两端架构、Torch、CUDA及SM87匹配后复用已构建二进制，SHA256与官方权重均核对一致，再做实际GPU测试；完整源码及构建补丁保留，其他设备不应跳过匹配检查直接复用。

实际conda清单与pip版本分别保存在`reports/decoder-conda-explicit-aarch64.txt`、`reports/decoder-runtime-pins.txt`。解码端`pip check`通过。安装后磁盘约剩7.5GiB，项目含环境约4.1GiB。最初两端为MAXN_SUPER；编码端出现OC3限速后，两端现已验证25W（nvpmodel模式3）实际限制生效，编码端启动顺序问题通过文末补丁修复。未锁定时钟，未修改保护阈值。

## 从 GitHub 重建项目

仓库不包含 `.env`、`vendor/DCVC`、CUTLASS、模型权重和测试视频。新设备执行：

```bash
git clone git@github.com:pengjunjie04/DCVC.git
cd DCVC
./tools/bootstrap.sh
```

脚本会拉取固定提交 `cbdae87a5445114cdc7f48816da63ea80bdeac40` 的 DCVC 和 `v4.4.1` CUTLASS，应用 `patches/jetson-build.patch`，创建项目环境并编译原生扩展。权重仍需按 README 放入 `checkpoints/`。如果已有 `.env`，可单独运行 `./tools/fetch_dcvc.sh`；脚本不会覆盖已修改的上游工作区。

## 日常启动

开机后在两端项目目录分别运行一键入口，先解码端、后编码端：

```bash
./start_decoder.sh
```

```bash
./start_encoder.sh
```

入口会检查 `.env`、25W 实际 CPU/GPU 限制和有线地址，地址缺失时尝试启用已有的 `DCVC-Direct`/`DCVC-Decoder` 有线连接；服务已运行时只打开现有页面，不会重复占用端口。默认页面分别为 `http://127.0.0.1:7861` 和 `http://127.0.0.1:7860`。`--check` 只做检查，`--no-browser` 不打开页面。

如需手动控制参数，解码端终端：

```bash
cd ~/Desktop/dcvc-jetson-demo
./launch_decoder.sh --port 9860
```

启动脚本会打开解码端本机浏览器 http://127.0.0.1:7861，直接显示解码画面、播放fps与两端处理速度。可使用 `--no-browser`，无界面模式用 `./receiver.sh --bind 192.168.50.2 --headless`。

若已有接收进程监听9860，无需再启动。当前后台接收进程的PID记录在解码端`reports/receiver-live.pid`，输出在`reports/receiver-live.log`；这是本次测试启动的进程，没有安装开机服务。

编码端终端：

```bash
cd ~/Desktop/dcvc-jetson-demo
./launch.sh
```

浏览器选择“双机发送 · HT-S”、“USB 摄像头”，在“设备与有线网络”填写本机192.168.50.1、解码端192.168.50.2，设置640×360、30fps，点击开始。首轮模型加载需要等待，暂停后继续会重新初始化。程序先请求 YUYV，再协商640×480@30，并读回格式、尺寸、帧率校验；驱动返回MJPG或模式不符时直接报错，不隐式回退。未压缩640×480帧保持比例补边到640×360，双缓冲已实测可达到30fps。真实协商统计见`reports/camera-yuyv-640x480-30fps.json`。

若需要重做浏览器功能验收，在两端服务均启动且编码端任务结束时运行：

```bash
DCVC_REQUIRE_POWER_MODE=25W .env/bin/python -s tests/browser_dual_host_smoke.py
```

测试依赖编码端现有Playwright及系统Chromium，仅保存统计，不录制视频、不截图。会实际操作开始、暂停、继续、结束、统计导出；另行报告性能目标，功能测试通过不代表所有性能指标均达标。

采集→canvas显示延迟验收需要第二台实际桌面Chromium开启CDP，并从编码端建立解码API与CDP隧道。本次使用`19222→第二台9222`和`17861→第二台7861`，运行：

```bash
DCVC_REQUIRE_POWER_MODE=25W \
DCVC_ENCODER_URL=http://127.0.0.1:7860 \
DCVC_DECODER_PAGE_URL=http://127.0.0.1:7861 \
DCVC_DECODER_API_URL=http://127.0.0.1:17861 \
DCVC_DECODER_CDP=http://127.0.0.1:19222 \
PYTHONNOUSERSITE=1 PYTHONPATH='' .env/bin/python -s tests/browser_display_latency.py
```

脚本只保存时间戳统计和状态，不保存画面。任一500ms目标为假或浏览器出现JS错误时，`status`会标记失败并返回非零；不得手工把失败报告改成通过。

## 性能优化与范围

RGB解码张量整组在GPU排列为连续HWC后一次拷贝到CPU；编码端整组一次上传并完成FP16颜色转换，接收端用八个线程并行生成展示JPEG。编码端使用独立响应线程，让下一组编码与远端解码重叠；最多两组在途，采集队列8帧、预览队列16帧，慢速或无响应接收端不会造成无限排队。每组真实码流顺序保持不变。

返回JPEG只用于展示，不是DCVC码流；模型码率不包含预览和协议开销。`oldest_to_host_ms`从该组最老采集帧算到编码端收到返回预览，`newest_to_host_ms`从该组最新帧算起；两者均未包含浏览器渲染。第二台页面另显示经跨机时钟校准的采集→canvas软件时延：预览突发以60fps排空，浏览器在解码前丢弃采集年龄超过475ms的过期帧并计入展示丢帧。该策略不降低模型30fps编解码吞吐，但实际canvas刷新率可能低于30fps。任何软件口径都不代表摄像头曝光到物理屏幕的完整时延。当前场景的低模型码率不能代表复杂动态场景。

原串行基线报告仅用于吞吐/时延对照：当时的测试脚本存在恢复旧计数的判定漏洞，不能用其status字段证明恢复成功。当前脚本已修复，最终报告的恢复状态确认新会话实际解码出帧。

## 重启后网络检查

编码端的原有DCVC-Direct配置未设置自动连接；重启后如果eno1没有192.168.50.1，运行 `nmcli connection up DCVC-Direct`，再ping解码端。该操作不更改Wi-Fi。第二台的有线地址也应先确认。页面中的速度口径与论文差异见 [指标说明](metrics-comparison.md)。

## 编码端25W启动顺序修复（已安装并验证）

第二次重启后仍发生相同错误。`reports/power-boot-order.txt`显示CDI刷新服务10.726秒开始，通过`nvidia-smi -L`探测GPU；功耗服务11.137秒才开始，随即报告golden context已创建而失败。该顺序很可能抢先初始化GPU，使TPC/FBP掩码无法设置。准备了独立systemd drop-in，使CDI刷新在nvpmodel之后运行；`systemd-analyze verify`返回0，无排序环，未禁用容器或修改功率阈值。

仅在编码端安装：

```bash
cd ~/Desktop/dcvc-jetson-demo
sudo install -D -m 644 tools/systemd/nvidia-cdi-refresh.service.d/20-jetson-power-order.conf /etc/systemd/system/nvidia-cdi-refresh.service.d/20-jetson-power-order.conf
sudo systemctl daemon-reload
sudo reboot
```

重启后用`nvpmodel -q --verbose`核对CPU MAX_FREQ=1497600、GPU MAX_FREQ=408000000、TPC mask=240、FBP mask=2，与配置一致。`nvpmodel.service`为oneshot，完成后可能是inactive；看`systemctl show nvpmodel -p Result -p ExecMainStatus`应success/0。用户已安装补丁并重启，核查Result=success、ExecMainStatus=0，实际CPU/GPU上限和TPC/FBP掩码均匹配25W配置。新的日志显示12.968秒功耗服务完成，12.996秒CDI刷新才开始；启动顺序问题已解决。证据见`reports/encoder-power-mode-fixed.txt`及`reports/power-boot-order-fixed.txt`。撤销时删除这一个drop-in文件、daemon-reload后重启即可。
