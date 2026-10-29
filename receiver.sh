#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export PYTHONNOUSERSITE=1
export PYTHONPATH="$PWD"
exec .env/bin/python -s -m demo.receiver "$@"
