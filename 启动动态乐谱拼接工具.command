#!/bin/bash
set -e
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

on_error() {
  local status=$?
  printf '\n启动失败，请查看上方提示。\n'
  if [ -t 0 ]; then
    printf '按回车关闭。\n'
    read -r answer || true
  fi
  exit "$status"
}
trap on_error ERR

compatible_python() {
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  printf '请先安装 FFmpeg。在终端执行：brew install ffmpeg\n'
  false
fi
if ! compatible_python .venv/bin/python; then
  interpreter=""
  # Homebrew's versioned executables may coexist with an older python3.
  for candidate in python3.12 python3.11 python3.13 python3.10 python3 python3.14; do
    if command -v "$candidate" >/dev/null 2>&1 && compatible_python "$candidate"; then
      interpreter="$(command -v "$candidate")"
      break
    fi
  done
  if [ -z "$interpreter" ]; then
    printf '需要 Python 3.10 或以上。请安装后重新双击启动：brew install python@3.11\n'
    false
  fi
  if [ -e .venv ] || [ -L .venv ]; then
    backup=".venv.backup-$(date +%Y%m%d-%H%M%S)-$$"
    mv .venv "$backup"
    printf '旧 Python 环境不兼容，已备份到 %s。\n' "$backup"
  fi
  printf '创建本地环境，使用 %s（%s）…\n' "$interpreter" "$("$interpreter" --version)"
  "$interpreter" -m venv .venv
fi
if ! .venv/bin/python -c 'import cv2, numpy, PIL' >/dev/null 2>&1; then
  printf '安装图像处理依赖（需要网络）…\n'
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python app.py "$@"
