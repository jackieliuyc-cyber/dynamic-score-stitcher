#!/bin/bash
set -e
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
trap 'printf "\n启动失败，请查看上方提示。按回车关闭。\n"; read -r answer' ERR
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  printf '请先安装 FFmpeg。在终端执行：brew install ffmpeg\n'
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  printf '首次启动：创建本地 Python 环境…\n'
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import cv2, numpy, PIL' >/dev/null 2>&1; then
  printf '首次启动：安装图像处理依赖（需要网络）…\n'
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python app.py "$@"
