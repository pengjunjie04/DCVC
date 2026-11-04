#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
source ./tools/start_common.sh

BIND='192.168.50.2'
PEER='192.168.50.1'
LISTEN_PORT=9860
WEB_PORT=7861
URL="http://127.0.0.1:${WEB_PORT}"
CHECK_ONLY=0
OPEN_BROWSER=1
HEADLESS=0
ARGS=()

for argument in "$@"; do
    case "$argument" in
        --check) CHECK_ONLY=1 ;;
        --headless) HEADLESS=1; OPEN_BROWSER=0; ARGS+=("$argument") ;;
        --no-browser) OPEN_BROWSER=0; ARGS+=("$argument") ;;
        *) ARGS+=("$argument") ;;
    esac
done

check_project_files
ensure_wired_ip "$BIND" DCVC-Direct DCVC-Decoder
ensure_25w
warn_unreachable_peer "$PEER"

if (( CHECK_ONLY )); then
    printf '解码端检查通过\n有线地址：%s\n功耗模式：25W\n接收端口：%s\n页面地址：%s\n' \
        "$BIND" "$LISTEN_PORT" "$URL"
    exit 0
fi

if http_ready "${URL}/"; then
    printf '解码端展示服务已运行：%s\n' "$URL"
    if (( OPEN_BROWSER )); then
        open_browser "$URL"
    fi
    exit 0
fi
if port_listening "$LISTEN_PORT" || port_listening "$WEB_PORT"; then
    die "接收端口 ${LISTEN_PORT} 或页面端口 ${WEB_PORT} 已被占用；若接收服务已在无界面模式运行，请先停止后重试。"
fi

printf '正在启动解码端：%s\n' "$URL"
exec ./launch_decoder.sh "${ARGS[@]}"
