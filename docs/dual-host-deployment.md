# 双机实机部署记录（2026-10-30）

两端项目均在 `~/Desktop/dcvc-jetson-demo`。编码端有线地址192.168.50.1/24；解码端jetson@yahboom，有线地址192.168.50.2/24。物理千兆链路，未配置有线默认网关，Wi-Fi继续承担上网与管理。

## 已验证的环境

两端均为Orin NX16GB、CUDA12.6、SM87，使用独立Miniforge和项目`.env` Python3.10、NVIDIA Torch2.5.0a0+872d972e41.nv24.08。没有替换系统Torch/CUDA，也没有修改解码端原有Miniconda环境或其他DCVC目录。

编码端L4T R36.4.7、系统cuDNN9.20.0；解码端R36.4.3、系统cuDNN9.6.0。原先仅检查出帧及速度遗漏了画质漂移。现已在解码端项目私有目录部署同版cuDNN9.20.0，两个启动器按项目设置加载，未替换系统库；首I帧会拒绝不一致的推理环境。257帧公开片段画质回归通过，详情见 [画质记录](quality-consistency.md)。

解码端安装了新的`~/miniforge3`，使用明确的conda包清单新建`.env`，再离线安装匹配的Python wheels。未直接搬移编码端的整个环境。两项原生扩展在确认两端架构、Torch、CUDA及SM87匹配后复用已构建二进制，SHA256与官方权重均核对一致，再做实际GPU测试；完整源码及构建补丁保留，其他设备不应跳过匹配检查直接复用。

实际conda清单与pip版本分别保存在`reports/decoder-conda-explicit-aarch64.txt`、`reports/decoder-runtime-pins.txt`。解码端`pip check`通过。安装后磁盘约剩7.5GiB，项目含环境约4.1GiB。最初两端为MAXN_SUPER；编码端出现OC3限速后，两端现已验证25W（nvpmodel模式3）实际限制生效，编码端启动顺序问题通过文末补丁修复。未锁定时钟，未修改保护阈值。

## 日常启动

解码端终端：

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

浏览器选择“双机发送 · HT-S”、“USB 摄像头”，在“设备与有线网络”填写本机192.168.50.1、解码端192.168.50.2，设置640×360、30fps，点击开始。首轮模型加载需要等待，暂停后继续会重新初始化。摄像头原生640×480 YUYV30，保持比例补边到640×360；双缓冲已实测可达到30fps。

若需要重做浏览器验收，在两端服务均启动且编码端任务结束时运行：

```bash
DCVC_REQUIRE_POWER_MODE=25W .env/bin/python -s tests/browser_dual_host_smoke.py
```

测试依赖编码端现有Playwright及系统Chromium，仅保存统计，不录制视频、不截图。会实际操作开始、暂停、继续、结束、统计导出；另行报告性能目标，功能测试通过不代表所有性能指标均达标。

## 性能优化与范围

RGB解码张量先在GPU排列为连续HWC，再拷贝CPU供JPEG预览，避免下游重复处理分平面内存。编码端使用独立响应线程，让下一组编码与远端解码重叠；最多两组在途，采集队列8帧、预览队列16帧，慢速或无响应接收端不会造成无限排队。每组真实码流顺序保持不变。

返回JPEG只用于展示，不是DCVC码流；模型码率不包含预览和协议开销。时延计量为采集端收到返回预览的耗时，未包含浏览器渲染，也不代表摄像头曝光到屏幕的完整时延。当前场景的低模型码率不能代表复杂动态场景。

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
