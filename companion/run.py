"""Entrypoint: uvicorn bound to 127.0.0.1 only."""
from __future__ import annotations

import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import load_config  # noqa: E402
from app.utils import FFMPEG_INSTALL_MSG, check_ffmpeg  # noqa: E402


def main() -> None:
    cfg = load_config()
    host = "127.0.0.1"  # never 0.0.0.0 — localhost only
    port = int(cfg.get("port", 8765))
    if not check_ffmpeg():
        print("ERROR: ffmpeg is required for merging 1080p+ and for MP3 conversion.")
        print(FFMPEG_INSTALL_MSG)
        print("The server will still start for testing, but downloads will fail until ffmpeg is installed.")
    print(f"Starting companion on http://{host}:{port} ...")
    print("Keep this window open while using the extension.")
    print("Update yt-dlp anytime with:  python -m pip install -U yt-dlp")
    import uvicorn
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
