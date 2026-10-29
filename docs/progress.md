# 当前状态（2026-10-30）

本机版本可运行：启动 ./launch.sh 打开 Gradio。官方 HT-S 和图像权重已下载，Miniforge .env 独立环境、rANS 和 CUDA 扩展均已验证。25 项自动化测试通过，正式权重160帧合成图案基准约166fps编码/141fps解码。真实独立进程解码通过；Gradio 浏览器解码预览实测30.0fps、采集到解码完成约0.4秒。完整原始记录在 reports/。

启停 GPU 缓存问题已修复：十轮正式模型启动/结束/暂停后 GPU 张量占用均回到0。暂停保留最后画面，继续重置模型状态。

未验收：USB摄像头（尚未插入）、第二台Jetson（尚未接入）、两端有线传输及跨机/浏览器完整延迟。当前已交付两端代码和接入说明；本机合成图案结果不能替代双机摄像头验收。

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
