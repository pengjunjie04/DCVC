# Sourced after changing into the project directory. Libraries affect this process only.
dcvc_cudnn_dir="${DCVC_CUDNN_LIB_DIR:-$HOME/.cache/dcvc-runtime/cudnn-9.20}"
if [[ -f "$dcvc_cudnn_dir/libcudnn.so.9" ]]; then
  export LD_LIBRARY_PATH="$dcvc_cudnn_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
elif [[ -n "${DCVC_CUDNN_LIB_DIR:-}" ]]; then
  echo "找不到指定的 cuDNN 运行库：$dcvc_cudnn_dir" >&2
  return 1
fi
unset dcvc_cudnn_dir
