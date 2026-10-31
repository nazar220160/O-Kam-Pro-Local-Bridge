#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ "$(uname -s)" != Darwin ]; then
  echo 'This launcher is for macOS. On Linux run: docker compose up -d' >&2
  exit 1
fi
command -v python3 >/dev/null || { echo 'Python 3.11+ is required.' >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo 'Install FFmpeg first: brew install ffmpeg' >&2; exit 1; }
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import cryptography' 2>/dev/null; then
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python scripts/native_host.py
