#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$ROOT"

build=1
if [[ "${1:-}" == "--no-build" ]]; then
  build=0
elif [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "用法: ./tools/bootstrap.sh [--no-build]"
  exit 0
elif [[ $# -gt 0 ]]; then
  echo "未知参数: $1" >&2
  exit 2
fi

if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "此流程面向 Jetson aarch64；当前架构为 $(uname -m)。" >&2
  exit 1
fi

if [[ -n "${CONDA_BIN:-}" ]]; then
  conda_bin="$CONDA_BIN"
elif command -v conda >/dev/null 2>&1; then
  conda_bin="$(command -v conda)"
elif [[ -x "$HOME/miniforge3/bin/conda" ]]; then
  conda_bin="$HOME/miniforge3/bin/conda"
else
  echo "未找到 conda。请先安装 Miniforge，并设置 CONDA_BIN 或加入 PATH。" >&2
  exit 1
fi

./tools/fetch_dcvc.sh

if [[ ! -x .env/bin/python ]]; then
  "$conda_bin" env create -p "$ROOT/.env" -f "$ROOT/environment.yml"
fi

PYTHONNOUSERSITE=1 .env/bin/python -s -m pip install -r requirements-lock.txt

if [[ "$build" == "1" ]]; then
  ./tools/build_codec.sh
fi

if [[ -f checkpoints/cvpr2026_image.pth.tar && -f checkpoints/cvpr2026_video_hts.pth.tar ]]; then
  PYTHONNOUSERSITE=1 .env/bin/python -s tools/check_weights.py
else
  echo "尚未找到两份官方权重，跳过权重校验。"
fi

cat <<'EOF'

依赖和原生扩展已准备。
下一步：将两份官方权重放入 checkpoints/，然后运行 ./launch.sh。
权重下载说明见 README.md 的“模型权重与构建”章节。
EOF
