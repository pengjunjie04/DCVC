#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONNOUSERSITE=1
export PYTHONPATH="$PWD"
export CUDA_HOME=/usr/local/cuda-12.6
export PATH="$PWD/.env/bin:$CUDA_HOME/bin:$PATH"
export MAX_JOBS="${MAX_JOBS:-1}"
python -s -c 'import torch; assert torch.cuda.is_available(); print(torch.__version__, torch.version.cuda, torch.cuda.get_device_capability())'
python -s -m pip install --no-build-isolation ./vendor/DCVC/src/cpp
cd vendor/DCVC/src/layers/extensions/inference
python -s -m pip install --no-build-isolation .
python -s -c 'import torch; import inference_extensions_cuda; print("CUDA inference extension ready")'
