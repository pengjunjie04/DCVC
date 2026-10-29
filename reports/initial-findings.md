# 本机初步检查

详见 environment.json。Python 3.10.12、NVIDIA Torch 2.5.0a0 nv24.08、CUDA 12.6、SM87；CUDA 可用。无 /dev/video*，与摄像头未插入一致。

已下载 DCVC 源码 cbdae87a5445114cdc7f48816da63ea80bdeac40、CUTLASS v4.4.1。尚未编译、运行模型或完成性能测试，未下载权重。

HT-S 源码 g_frame_delay=8，30fps 时一组首帧等待其余帧约为 7/30 秒，尚不含计算、传输和显示。真实 compress/decompress 依赖 CUDA 扩展，不能用训练 forward 代替。

上游 CPU 扩展 setup.py 声明 Python >=3.12；本机为 3.10。需验证兼容方案，不能仅以 README 的“其他版本可能可用”为成功依据。CUDA 扩展构建脚本会在可用内存低于 32GB 时设置 MAX_JOBS=8；本机编译需要限制并发以避免内存压力。

创建项目 .venv 首次因缺 ensurepip 失败，随后用 --without-pip --system-site-packages 创建成功。此为试验环境，不代表已具备完整依赖。获取 pybind11 时出现 PyPI TLS 连接错误。未替换系统 Torch/CUDA，未修改网络或功耗配置。Miniforge 未安装。

已阅读用户提供 Jetson guide README。仓库目录中的多项安装/网络教程仅列标题，实际决策仍需依据本机检测及 NVIDIA 官方文档。
