#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
exec ./receiver.sh --bind "${DCVC_DECODER_BIND:-192.168.50.2}" "$@"
