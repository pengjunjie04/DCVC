#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .env/bin/python ]]; then
  echo '尚未配置项目环境，请阅读 README.md。' >&2
  exit 1
fi
export PYTHONNOUSERSITE=1
export PYTHONPATH="$PWD"
export GRADIO_ANALYTICS_ENABLED=False
export CUDA_HOME=/usr/local/cuda-12.6
exec .env/bin/python -s -m demo.app "$@"
