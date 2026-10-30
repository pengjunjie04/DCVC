# 双机画质一致性修复（2026-10-30）

用户反馈第二台画面像水流、模糊。之前的浏览器验收只证明解码出帧及播放速度，没有检验跨设备重建画质，这项验收存在遗漏。

## 复现与定位

使用同一公开OpenCV vtest.avi片段、640×360、官方HT-S权重、QP32，比较第1帧至257帧。没有保存任何摄像头图像。两端权重、扩展及codec适配器的SHA256均一致。

| 对照 | 首帧RGB PSNR | 最后一组RGB PSNR | 说明 |
|---|---:|---:|---|
| 同机独立编码/解码状态 | 32.26dB | 约32dB | 未经JPEG，稳定 |
| 原双机，cuDNN9.20→9.6 | 31.50dB | 19.13dB | 包含JPEG75，持续劣化 |
| 双机均设置上游确定性选项，库版本仍不同 | 31.50dB | 第129帧20.22dB | 仅确定性选项不能解决 |
| 双机统一cuDNN9.20，正式启动脚本 | 31.51dB | 31.34dB | 257帧稳定，最差单帧30.48dB，包含JPEG75 |

提高QP到63并没有消除旧环境下的劣化。受控实验只替换诊断用解码进程的cuDNN版本即可恢复一致画质，故定位到两端数值运行库差异引发的跨帧问题；尚未逐一定位内部算子。不应把这个现象解释为一般的有损压缩模糊。

当前实际版本是编码端cuDNN9.20.0、解码端系统cuDNN9.6.0；之前环境记录中的9.2是对9.20的错误简写。统一后的私有库在解码端`~/.cache/dcvc-runtime/cudnn-9.20`，约1GiB。系统库、系统CUDA/Torch及其他应用均未替换。两端启动器读取`tools/runtime_env.sh`，优先使用该私有目录；可通过`DCVC_CUDNN_LIB_DIR`指定明确路径，指定但缺失会拒绝启动。库校验记录见`reports/private-cudnn-manifest.json`。

## 防止复发

首I帧携带Torch、CUDA、cuDNN及GPU计算架构信息；解码器在调用原生解码前检查一致性，缺失或不同则拒绝。更换库后必须重新启动进程。版本相同并不替代权重、扩展校验及实际画质回归。

```bash
# 两端服务先启动；编码端保持采集停止。只发送已有视频文件，不录制摄像头。
.env/bin/python -s tools/check_quality.py --output reports/quality-check.json
```

默认公开片段、QP32的每帧RGB PSNR门槛30dB。其他输入/QP需要选择相应门槛，不把该门槛当作所有场景的画质标准。报告包含预览JPEG75的影响，不是论文直接从模型重建帧计算的质量分数，也不是30fps性能验收。工具在新增OC事件时停止。

原始证据：`quality-wired-probe.json`、`quality-local-probe.json`、`quality-deterministic-probe.json`、`quality-aligned-probe.json`、`quality-wired-fixed.json`。旧的双机速度报告不能单独证明画质正确。

该DCVC模型的QP方向与常见传统编码器不同：在此权重实测QP越大，质量及码率越高。360p放大显示仍有分辨率限制，但不应出现此次持续漂移。
