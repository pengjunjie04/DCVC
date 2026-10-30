# 当前状态（2026-10-30）

项目位于`~/Desktop/dcvc-jetson-demo`，两端独立Miniforge、官方HT-S权重与CUDA/rANS扩展已部署。编码端运行`./launch.sh`（7860），解码端运行`./launch_decoder.sh`（7861）。新界面包含双监视器、实时吞吐/处理速度/ms每帧、实际浏览器绘制fps、统计导出与启停控件；解码端本机也能直接播放并查看两端速度。36项CPU自动化测试通过，桌面与390px窄屏合成输入布局检查通过，不保存摄像头图像。

真实摄像头双屏测试通过开始/暂停/恢复新帧/结束/统计导出，68秒内解码29.92fps，第二台实际桌面浏览器绘制中位数29.9fps；返回预览时延中位数551.1ms、最大622.9ms。≤500ms未达标，完整显示时延未测。详细口径见`metrics-comparison.md`。

**当前阻碍：** 编码端OC3事件。用户选择25W后模式名称正确，但实际GPU上限1173MHz、CPU1984MHz仍未降到配置408MHz/1497.6MHz，nvpmodel开机服务记录要求重启并失败。短测新增6次OC3已自动停止，解码端限制正确且OC为0。再次重启后仍失败；启动日志发现CDI刷新服务先于nvpmodel调用nvidia-smi，疑似提前初始化GPU。已准备systemd启动顺序drop-in并通过排序验证，等待用户在编码端安装并重启，再核查硬件限制及25W稳态表现。未修改保护阈值或锁定时钟，尚不能宣称项目性能目标全部完成。

本轮完整代码审查已处理共享内存IPC、结束时最后帧轮询、模型异常状态传播与最后邮箱读取竞态。GPU→RGB批量转换实验只节省约3ms/8帧，暂不引入额外实现，优先解决有效功耗模式与实测延迟。

下方为历史工作记录。

# Progress

User authorized continuous work and all functional requirements. No additional hardware information is needed for local development. Second host and camera absent.

Ruling: implement inline with one final fresh review; avoid approval loops because the user explicitly requested continuation.
Ruling: use a new local repository on work/demo in the exact requested Desktop directory; no existing repository needs a separate worktree.
Task 1: in progress. Source and CUTLASS fetched, system probe recorded. Miniforge download in progress. Upstream uses Python 3.12 f-string syntax in benchmark script, but inference modules will be checked for Python 3.10 compatibility.

Task 2: complete: config/framing/rates tests green. Task 3: local capture lifecycle and bounded capture tested; independent codec adapter and TCP receiver written, actual model validation pending. Preview pacing regression reproduced (145 < 150) and fixed by an independent bounded playback thread; suite green afterward. Task 4: Gradio written; first startup identified missing socksio for existing SOCKS proxy, installing dependency.
Environment: Miniforge installed at ~/miniforge3, project .env Python 3.10 created via conda-forge mirror. Python deps installed from PyPI via proxy, NVIDIA wheel resumable download in progress. Upstream modules pass Python 3.10 compileall; compatibility patch relaxes CPU extension metadata and limits CUDA build jobs. Official OneDrive checkpoint API returned 401 for primary/backup links; no unofficial weights used.

2026-10-29 update: independent Miniforge .env installed NVIDIA torch2.5 nv24.08; CUDA available SM87 confirmed. CPU rANS built/imported. pip check clean after sympy pin. Gradio server started and browser interaction test passed start/pause/resume/stop with no page errors; synthetic capture measured30fps. Screenshot reports/ui-capture.png. CUDA extension compiling single-job; native DMCI/HTS methods patched to release GIL during work and reacquire before Python output construction. Full official model benchmark still pending.
Independent review found no remaining Critical/Important blockers for trusted wired demo scope after fixes. Receiver now uses spawned session process and180s progress watchdog; malformed native entropy cannot crash listener. Python metadata/offset checks, deep JSON, same-size P guard and safe JPEG/timing guards implemented. Minor unbounded metrics history fixed.24 tests passing. Blocked camera read cannot be forcibly canceled in Python; alive tracking refuses unsafe restart; hardware acceptance pending.
Official OneDrive public folder successfully rendered in fresh anonymous browser (direct API401). Two official filenames visible; browser download in progress.

CUDA extension compiled and installed successfully (18MB .so). Import verified after importing torch (build check updated accordingly). CUDA/cuDNN FP16 convolution check passed. Random-weight architecture smoke: independent encoder/decoder correctly handled I(1 frame)+P(8)+P(8), genuine entropy bytes with3/3/1 parallel streams. No official performance/quality claim. Native GIL regression runtime check:27.18ms native call with25 heartbeat ticks, so capture/UI Python threads remain runnable. reports/untrained-smoke.json. Browser rerun:30.2 actual drawn FPS on synthetic capture, no JS errors. Official file fetching still being retried; a failed0-byte image artifact is rejected by readiness and will be replaced/deleted.

Official OneDrive weight downloads completed via anonymous browser cookies + Referer/User-Agent replay: image168845375 bytes, HT-S324891626 bytes. SHA256 saved in reports/official-weight-downloads.json. Both weights loaded successfully. Official160-frame moving-pattern benchmark QP32 (3 warmup groups excluded): encode165.94fps, decode141.48fps, content0.013341Mbps at30fps. This easy generated pattern is not a camera/dual-host acceptance test. Pretrained independent encoder/decoder processes passed17-frame serialized-wire round trip. Concurrent separate CUDA processes on one16GB device hit OOM; sequential independent processes pass.
Repeated Engine restart exposed native buffer cache retention and occasional second-start OOM. Added explicit Codec.close, garbage collection, native tensor pool release binding and cache emptying after both codecs close. Hardware3-cycle restart regression in progress;25 unit tests passing.

Final local verification: native pool cleanup3 cycles passed (0 CUDA tensor bytes after each stop/pause), fresh browser official-model session including resume17 frames passed, preview30.0fps. Timing samples ~0.4s to host reconstruction, not browser glass-to-glass. Launcher also started successfully from /tmp on alternate port7861. Test server will be shut down after verification so ./launch.sh can start cleanly.

Extended final hardware regression:10 consecutive real HT-S cycles passed, each17 frames decoded; all10 returned CUDA tensor allocation to0. Browser latest session passed start/pause/resume/end plus stats-file export. UI now shows readable device status, current latency and dropped frames. Test services shut down; launch.sh ready for clean user startup.

Additional natural-content check: official OpenCV vtest.avi (source10fps, not a30fps capture claim),160 measured frames rescaled/letterboxed640x360, QP32: encode147.89fps/decode129.75fps; recorded in reports/natural-clip-benchmark.json and natural-clip-source.json. Source clip kept outside git in tools/testdata.
