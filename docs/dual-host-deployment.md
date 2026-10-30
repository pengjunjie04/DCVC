# 双机实机部署记录（2026-10-30）

两端项目均在 `~/Desktop/dcvc-jetson-demo`。编码端有线地址192.168.50.1/24；解码端jetson@yahboom，有线地址192.168.50.2/24。物理千兆链路，未配置有线默认网关，Wi-Fi继续承担上网与管理。

## 已验证的环境

两端均为Orin NX16GB、CUDA12.6、SM87，使用独立Miniforge和项目`.env` Python3.10、NVIDIA Torch2.5.0a0+872d972e41.nv24.08。没有替换系统Torch/CUDA，也没有修改解码端原有Miniconda环境或其他DCVC目录。

编码端L4T R36.4.7/cuDNN9.2，解码端R36.4.3/cuDNN9.6。此次差异已通过实际FP16 CUDA卷积、CPU/CUDA原生扩展导入及官方模型真实摄像头码流解码验证；不把它推广为任意JetPack版本兼容承诺。

解码端安装了新的`~/miniforge3`，使用明确的conda包清单新建`.env`，再离线安装匹配的Python wheels。未直接搬移编码端的整个环境。两项原生扩展在确认两端架构、Torch、CUDA及SM87匹配后复用已构建二进制，SHA256与官方权重均核对一致，再做实际GPU测试；完整源码及构建补丁保留，其他设备不应跳过匹配检查直接复用。

实际conda清单与pip版本分别保存在`reports/decoder-conda-explicit-aarch64.txt`、`reports/decoder-runtime-pins.txt`。解码端`pip check`通过。安装后磁盘约剩7.5GiB，项目含环境约4.1GiB。未改电源模式或锁定时钟，两端已有MAXN_SUPER配置。

## 日常启动

解码端终端：

```bash
cd ~/Desktop/dcvc-jetson-demo
./receiver.sh --bind 192.168.50.2 --port 9860
```

若已有接收进程监听9860，无需再启动。当前后台接收进程的PID记录在解码端`reports/receiver-live.pid`，输出在`reports/receiver-live.log`；这是本次测试启动的进程，没有安装开机服务。

编码端终端：

```bash
cd ~/Desktop/dcvc-jetson-demo
./launch.sh
```

浏览器选择“双机发送 · HT-S”、“USB 摄像头”，在“设备与有线网络”填写本机192.168.50.1、解码端192.168.50.2，设置640×360、30fps，点击开始。首轮模型加载需要等待，暂停后继续会重新初始化。摄像头原生640×480 YUYV30，保持比例补边到640×360；双缓冲已实测可达到30fps。

若需要重做浏览器验收，在两端服务均启动且编码端任务结束时运行：

```bash
.env/bin/python -s tests/browser_dual_host_smoke.py
```

测试依赖编码端现有Playwright及系统Chromium，仅保存统计，不录制视频、不截图。会实际操作开始、暂停、继续、结束、统计导出；另行报告性能目标，功能测试通过不代表所有性能指标均达标。

## 性能优化与范围

RGB解码张量先在GPU排列为连续HWC，再拷贝CPU供JPEG预览，避免下游重复处理分平面内存。编码端使用独立响应线程，让下一组编码与远端解码重叠；最多两组在途，采集队列8帧、预览队列16帧，慢速或无响应接收端不会造成无限排队。每组真实码流顺序保持不变。

返回JPEG只用于展示，不是DCVC码流；模型码率不包含预览和协议开销。时延计量为采集端收到返回预览的耗时，未包含浏览器渲染，也不代表摄像头曝光到屏幕的完整时延。当前场景的低模型码率不能代表复杂动态场景。

原串行基线报告仅用于吞吐/时延对照：当时的测试脚本存在恢复旧计数的判定漏洞，不能用其status字段证明恢复成功。当前脚本已修复，最终报告的恢复状态确认新会话实际解码出帧。
