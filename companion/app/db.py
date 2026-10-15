"""SQLite history store (thread-safe)."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

_lock = threading.Lock()
SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT,
  item_id TEXT,
  url TEXT,
  title TEXT,
  channel TEXT,
  quality TEXT,
  container TEXT,
  audio_only INTEGER DEFAULT 0,
  filepath TEXT,
  filesize INTEGER DEFAULT 0,
  status TEXT DEFAULT 'queued',
  error TEXT DEFAULT '',
  created_at TEXT,
  completed_at TEXT
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        conn = _connect(db_path)
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def add_entry(db_path: Path, entry: dict) -> int:
    with _lock:
        conn = _connect(db_path)
        try:
            cur = conn.execute(
                """INSERT INTO downloads
                   (job_id,item_id,url,title,channel,quality,container,audio_only,filepath,filesize,status,error,created_at,completed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    entry.get("job_id", ""), entry.get("item_id", ""), entry.get("url", ""),
                    entry.get("title", ""), entry.get("channel", ""), entry.get("quality", ""),
                    entry.get("container", ""), int(bool(entry.get("audio_only", False))),
                    entry.get("filepath", ""), int(entry.get("filesize", 0) or 0),
                    entry.get("status", "queued"), entry.get("error", ""),
                    entry.get("created_at") or now_iso(), entry.get("completed_at", ""),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def update_entry(db_path: Path, row_id: int, fields: dict) -> None:
    if not fields:
        return
    keys = list(fields.keys())
    vals = [fields[k] for k in keys] + [row_id]
    with _lock:
        conn = _connect(db_path)
        try:
            conn.execute(
                f"UPDATE downloads SET {', '.join(f'{k}=?' for k in keys)} WHERE id=?",
                vals,
            )
            conn.commit()
        finally:
            conn.close()


def list_entries(db_path: Path, limit: int = 100) -> list[dict]:
    with _lock:
        conn = _connect(db_path)
        try:
            cur = conn.execute(
                "SELECT * FROM downloads ORDER BY id DESC LIMIT ?", (int(limit),)
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


def get_entry(db_path: Path, row_id: int) -> dict | None:
    with _lock:
        conn = _connect(db_path)
        try:
            cur = conn.execute("SELECT * FROM downloads WHERE id=?", (row_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
