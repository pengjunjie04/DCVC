#!/usr/bin/env bash

die() {
    printf '错误：%s\n' "$*" >&2
    exit 1
}

has_ipv4() {
    local address="$1"
    ip -4 -o addr show 2>/dev/null | grep -Fq " ${address}/"
}

ensure_wired_ip() {
    local address="$1"
    shift
    has_ipv4 "$address" && return 0
    if command -v nmcli >/dev/null 2>&1; then
        local connection name attempt
        for name in "$@"; do
            if nmcli -t -f NAME connection show 2>/dev/null | grep -Fxq "$name"; then
                connection="$name"
                break
            fi
        done
        if [[ -n "${connection:-}" ]]; then
            printf '有线地址 %s 未就绪，正在启用 %s...\n' "$address" "$connection"
            nmcli connection up "$connection" >/dev/null 2>&1 || true
            for attempt in $(seq 1 10); do
                has_ipv4 "$address" && return 0
                sleep 0.5
            done
        fi
    fi
    die "未检测到有线地址 ${address}/24。请确认网线已连接，并运行 ip -4 -br addr 检查。"
}

ensure_25w() {
    local mode cpu_max gpu_max tpc_mask fbp_mask
    mode="$(nvpmodel -q 2>/dev/null || true)"
    if [[ "$mode" != *'NV Power Mode: 25W'* ]]; then
        die "当前不是 25W 模式。请运行 sudo nvpmodel -m 3，重启后重新执行本脚本。"
    fi
    cpu_max="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq 2>/dev/null || true)"
    gpu_max="$(cat /sys/devices/platform/17000000.gpu/devfreq_dev/max_freq 2>/dev/null || true)"
    tpc_mask="$(cat /sys/devices/platform/gpu.0/tpc_pg_mask 2>/dev/null || true)"
    fbp_mask="$(cat /sys/devices/platform/gpu.0/fbp_pg_mask 2>/dev/null || true)"
    if [[ "$cpu_max" != '1497600' || "$gpu_max" != '408000000' ||
            "$tpc_mask" != '240' || "$fbp_mask" != '2' ]]; then
        die "25W 模式名称已生效，但实际限制不匹配（CPU=${cpu_max:-未知}, GPU=${gpu_max:-未知}, TPC=${tpc_mask:-未知}, FBP=${fbp_mask:-未知}）。请重启并检查 nvpmodel 启动顺序。"
    fi
}

port_listening() {
    local port="$1"
    ss -ltnH "sport = :${port}" 2>/dev/null | grep -q .
}

http_ready() {
    curl -fsS --max-time 1 "$1" >/dev/null 2>&1
}

open_browser() {
    local url="$1"
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" >/dev/null 2>&1 &
    else
        python3 -c 'import sys, webbrowser; webbrowser.open(sys.argv[1])' "$url" >/dev/null 2>&1 &
    fi
}

check_project_files() {
    [[ -x .env/bin/python ]] || die '缺少项目环境 .env；这不是常规开机启动问题，请先按 README 恢复环境。'
    [[ -d vendor/DCVC ]] || printf '提示：vendor/DCVC 不存在，模型模式可能无法启动。\n' >&2
    local weight
    for weight in checkpoints/cvpr2026_image.pth.tar checkpoints/cvpr2026_video_hts.pth.tar; do
        [[ -f "$weight" ]] || printf '提示：缺少模型权重 %s，模型模式可能无法启动。\n' "$weight" >&2
    done
}

warn_unreachable_peer() {
    local peer="$1"
    if ! ping -c 1 -W 1 "$peer" >/dev/null 2>&1; then
        printf '提示：暂时 ping 不通 %s；请确认另一台 Jetson 已运行对应脚本。\n' "$peer" >&2
    fi
}
