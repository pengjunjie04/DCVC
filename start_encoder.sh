#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
source ./tools/start_common.sh

BIND='192.168.50.1'
PEER='192.168.50.2'
PORT=7860
URL="http://127.0.0.1:${PORT}"
CHECK_ONLY=0
OPEN_BROWSER=1
ARGS=()

for argument in "$@"; do
    case "$argument" in
        --check) CHECK_ONLY=1 ;;
        --no-browser) OPEN_BROWSER=0; ARGS+=("$argument") ;;
        *) ARGS+=("$argument") ;;
    esac
done

check_project_files
ensure_wired_ip "$BIND" DCVC-Direct
ensure_25w
warn_unreachable_peer "$PEER"

camera_count=$(compgen -G '/dev/video*' | wc -l)
if (( camera_count == 0 )); then
    printf '提示：未检测到 /dev/video*；可使用测试图案，但 USB 摄像头模式不可用。\n' >&2
fi

if (( CHECK_ONLY )); then
    printf '编码端检查通过\n有线地址：%s\n功耗模式：25W\n摄像头节点：%s\n页面地址：%s\n' \
        "$BIND" "$( ((camera_count > 0)) && printf '/dev/video0 等 %s 个节点' "$camera_count" || printf '未检测到')" "$URL"
    exit 0
fi

if http_ready "${URL}/api/state"; then
    printf '编码端服务已运行：%s\n' "$URL"
    if (( OPEN_BROWSER )); then
        open_browser "$URL"
    fi
    exit 0
fi
if port_listening "$PORT"; then
    die "端口 ${PORT} 已被其他程序占用；请先关闭占用程序。"
fi

printf '正在启动编码端：%s\n' "$URL"
exec ./launch.sh "${ARGS[@]}"
