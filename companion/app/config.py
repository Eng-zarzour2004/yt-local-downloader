"""Config load/save + first-run token generation."""
from __future__ import annotations

import json
import secrets
from pathlib import Path

COMPANION_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = COMPANION_DIR / "config.json"
DEFAULT_DOWNLOADS_DIR = Path.home() / "Downloads" / "YTDownloader"

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8765,
    "download_dir": str(DEFAULT_DOWNLOADS_DIR),
    "max_concurrent": 2,
    "token": "",
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
        except Exception:
            pass
    # Generate token on first run
    if not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(32)
        save_config(cfg)
    # Ensure download dir exists
    try:
        Path(cfg["download_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def get_download_dir(cfg: dict) -> Path:
    p = Path(cfg.get("download_dir") or str(DEFAULT_DOWNLOADS_DIR)).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p
