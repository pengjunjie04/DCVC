#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DCVC_REPO="${DCVC_REPO:-https://github.com/microsoft/DCVC.git}"
DCVC_COMMIT="${DCVC_COMMIT:-cbdae87a5445114cdc7f48816da63ea80bdeac40}"
CUTLASS_REPO="${CUTLASS_REPO:-https://github.com/NVIDIA/cutlass.git}"
CUTLASS_COMMIT="${CUTLASS_COMMIT:-4370102f9dacab813282e1d67722fceb0b90a019}"
VENDOR_DIR="${DCVC_VENDOR_DIR:-$ROOT/vendor/DCVC}"
CUTLASS_DIR="$VENDOR_DIR/third_party/cutlass"
PATCH="$ROOT/patches/jetson-build.patch"

die() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

checkout_pinned() {
  local directory="$1" repository="$2" commit="$3" label="$4"
  if [[ -e "$directory" && ! -d "$directory/.git" ]]; then
    die "$label 目录存在但不是 Git 仓库：$directory"
  fi
  if [[ ! -d "$directory/.git" ]]; then
    mkdir -p "$(dirname -- "$directory")"
    git init -q "$directory"
  fi
  if git -C "$directory" remote get-url origin >/dev/null 2>&1; then
    git -C "$directory" remote set-url origin "$repository"
  else
    git -C "$directory" remote add origin "$repository"
  fi
  if [[ "$(git -C "$directory" rev-parse HEAD 2>/dev/null || true)" != "$commit" ]]; then
    if [[ -n "$(git -C "$directory" status --porcelain 2>/dev/null || true)" ]]; then
      die "$label 位于非目标提交且有本地修改，拒绝覆盖：$directory"
    fi
    git -C "$directory" fetch --depth 1 origin "$commit"
    git -C "$directory" checkout -q --detach FETCH_HEAD
  fi
  if [[ "$(git -C "$directory" rev-parse HEAD)" != "$commit" ]]; then
    die "$label 未能切换到固定提交 $commit"
  fi
}

checkout_pinned "$VENDOR_DIR" "$DCVC_REPO" "$DCVC_COMMIT" "DCVC"

if git -C "$VENDOR_DIR" apply --check "$PATCH" >/dev/null 2>&1; then
  git -C "$VENDOR_DIR" apply "$PATCH"
  echo "已应用 Jetson 兼容补丁：patches/jetson-build.patch"
elif git -C "$VENDOR_DIR" apply --reverse --check "$PATCH" >/dev/null 2>&1; then
  echo "Jetson 兼容补丁已应用"
else
  die "补丁无法应用，请检查 vendor/DCVC 是否被其他修改污染"
fi

checkout_pinned "$CUTLASS_DIR" "$CUTLASS_REPO" "$CUTLASS_COMMIT" "CUTLASS"

printf 'DCVC  %s\n' "$(git -C "$VENDOR_DIR" rev-parse HEAD)"
printf 'CUTLASS %s\n' "$(git -C "$CUTLASS_DIR" rev-parse HEAD)"
printf '上游源码已准备：%s\n' "$VENDOR_DIR"
