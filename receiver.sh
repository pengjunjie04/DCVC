#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
source ./tools/runtime_env.sh
export PYTHONNOUSERSITE=1
export PYTHONPATH="$PWD"
exec .env/bin/python -s -m demo.receiver "$@"
