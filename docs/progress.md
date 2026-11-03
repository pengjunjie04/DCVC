# 当前状态（2026-11-03）

项目`~/Desktop/dcvc-jetson-demo`已部署两端独立环境、官方HT-S权重和原生扩展。编码端`./launch.sh`打开7860，解码端`./launch_decoder.sh`打开7861，在第二台屏幕播放并展示两端实时速度。39项CPU自动化测试通过；编码/解码吞吐、处理fps及ms/帧、浏览器实际绘制fps、统计导出和启停均已实现。

2026-11-03 可复现性补强：新增 `tools/fetch_dcvc.sh` 和 `tools/bootstrap.sh`，从固定 DCVC/CUTLASS 提交重建上游源码并应用补丁；`requirements-lock.txt` 已移除本机绝对路径。GitHub 仓库仍不包含环境、权重、测试视频和 `vendor/`。

编码端启动顺序故障已修复并验证：nvpmodel先于CDI GPU探测运行，两端实际硬件限制均匹配25W。此前用户看到的水流样画质异常已复现并定位到两端cuDNN9.20/9.6不一致。仅为项目进程统一到9.20后，257帧公开视频画质稳定，末组RGB PSNR31.34dB、最差单帧30.48dB（含JPEG75）。没有替换系统CUDA/Torch或解码端系统库，没有保存摄像头画面。首I帧现在检查推理环境，缺失或不匹配即拒绝原生解码。细节及证据见`quality-consistency.md`。

最终真实摄像头双屏复测：69.35秒稳态，编码/解码29.99fps，第二台实际桌面浏览器绘制中位数29.9fps；三个稳态丢帧计数均0、两端OC计数均0。处理速度中位数编码50.37fps/解码47.74fps；启停、恢复新帧及导出通过。报告`reports/dual-display-camera-browser-quality-fixed.json`。公开视频画质回归与摄像头吞吐验收分别计量，摄像头主观观感仍可由用户确认。

2026-11-03 低延迟改造：整组一次性 H2D/颜色转换、解码端整组 GPU 输出后一次拷贝、FP16 颜色转换、接收端四线程并行 JPEG 预览，并补充组帧等待、最老帧和最新帧分解。真实双机摄像头连续40个稳态样本：返回预览口径最老帧中位数478.9ms、最大490.8ms，已低于500ms；最新帧中位数245.3ms。采集丢帧增量为0，两端OC计数为0。报告`reports/dual-host-latency-25w.json`。

**尚未完成：** 返回预览已达标，但完整“摄像头采集→第二台浏览器canvas绘制”时延尚未实测；长时间运行、不同动态场景与其他参数组合还需迭代验收。

本轮代码审查已处理IPC与结束帧竞态；运行库匹配与启动器修复另经独立审查，无Critical/Important发现。39项测试包括新增的运行库不一致预解码拒绝检查。

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
