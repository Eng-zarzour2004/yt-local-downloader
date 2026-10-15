#!/usr/bin/env bash
# Start the YT Downloader companion (macOS / Linux). Binds to 127.0.0.1:8765 only.
set -e
cd "$(dirname "$0")"
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "WARNING: ffmpeg not found on PATH."
  echo "  macOS: brew install ffmpeg"
  echo "  Ubuntu/Debian: sudo apt install ffmpeg"
  echo "  Fedora: sudo dnf install ffmpeg"
  echo ""
fi
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python run.py
