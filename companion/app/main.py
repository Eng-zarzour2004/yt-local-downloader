"""Companion server: FastAPI bound to 127.0.0.1, token auth, strict CORS, SSE progress."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import db as dbmod
from .config import COMPANION_DIR, get_download_dir, load_config, save_config
from .downloader import DownloadManager
from .utils import (
    YTDL_JS_RUNTIMES,
    FFMPEG_INSTALL_MSG,
    available_quality_options,
    canonical_playlist_url,
    canonical_video_url,
    check_ffmpeg,
    ffmpeg_version,
    format_duration,
    friendly_yt_error,
    split_youtube_url,
)

VERSION = "1.0.0"

cfg = load_config()
DB_PATH = COMPANION_DIR / "history.db"
dbmod.init_db(DB_PATH)
manager = DownloadManager(cfg, DB_PATH)

app = FastAPI(title="YT Downloader Companion", version=VERSION)

# Strict CORS: only extension origins + localhost call the server.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"(chrome-extension://.*|moz-extension://.*|safari-web-extension://.*|https?://127\.0\.0\.1(:\d+)?|https?://localhost(:\d+)?)",
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def current_token() -> str:
    return str(cfg.get("token", ""))


async def require_auth(request: Request,
                       authorization: str | None = Header(default=None),
                       token: str | None = Query(default=None)):
    expected = current_token()
    provided = ""
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    elif token:
        provided = token.strip()  # EventSource cannot set headers, so ?token= is allowed
    if not expected or provided != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API token. Paste the token from the companion console into the extension options page.")
    return True


# ---------- models ----------
class InfoRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    quality: str = "best"  # best|2160|1440|1080|720|480
    container: str = "mp4"  # mp4|mkv
    audio_only: bool = False
    audio_format: str = "mp3"  # mp3|m4a
    audio_bitrate: str = "192"  # 192|320
    download_playlist: bool = False
    playlist_url: str | None = None  # canonical playlist URL when scope = whole playlist


class SettingsRequest(BaseModel):
    download_dir: str | None = None
    max_concurrent: int | None = Field(default=None, ge=1, le=5)


def ytdlp_version() -> str:
    try:
        import yt_dlp
        v = getattr(yt_dlp, "__version__", None)
        if v:
            return str(v)
        from yt_dlp.version import __version__ as vv  # type: ignore

        return str(vv)
    except Exception:
        return "?"


# ---------- public ----------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": VERSION,
        "ffmpeg": check_ffmpeg(),
        "ffmpeg_version": ffmpeg_version(),
        "ytdlp_version": ytdlp_version(),
        "download_dir": str(cfg.get("download_dir")),
        "active_downloads": manager.active_count(),
    }


# ---------- info ----------
def _probe_playlist_summary(pl_url: str) -> dict | None:
    """Cheap flat probe of a playlist URL. Returns {id,url,title,count} or None."""
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                               "js_runtimes": dict(YTDL_JS_RUNTIMES),
                               "extract_flat": True, "noplaylist": False}) as ydl:
            flat = ydl.extract_info(pl_url, download=False)
    except Exception:
        return None
    if not flat or flat.get("_type") != "playlist":
        return None
    entries = [e for e in (flat.get("entries") or []) if e]
    return {"id": flat.get("id") or "",
            "url": flat.get("webpage_url") or pl_url,
            "title": flat.get("title") or "Playlist",
            "count": flat.get("playlist_count") or len(entries)}


@app.post("/info", dependencies=[Depends(require_auth)])
def fetch_info(body: InfoRequest):
    import yt_dlp

    url = (body.url or "").strip()
    if not url or ("youtube.com" not in url and "youtu.be" not in url):
        raise HTTPException(status_code=400, detail="Invalid URL. Paste a youtube.com/watch, youtu.be, /shorts, or playlist URL.")
    parts = split_youtube_url(url)

    # Pure playlist URL (/playlist?list=...) -> playlist branch (unchanged behaviour)
    if parts["is_playlist_url"] and not parts["video_id"]:
        pl_url = canonical_playlist_url(url) or url
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                   "js_runtimes": dict(YTDL_JS_RUNTIMES),
                                   "extract_flat": True, "noplaylist": False}) as ydl:
                flat = ydl.extract_info(pl_url, download=False)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=friendly_yt_error(exc))
        if flat is None or flat.get("_type") != "playlist":
            raise HTTPException(status_code=400, detail="Could not read that playlist.")
        raw_entries = [e for e in (flat.get("entries") or []) if e][:50]
        entries = []
        for e in raw_entries:
            vid = e.get("id") or ""
            vurl = e.get("url") or ""
            # Flat playlist entries sometimes give a bare video id instead of a URL.
            if vurl.startswith("/"):
                vurl = "https://www.youtube.com" + vurl
            elif not vurl.startswith("http"):
                vurl = f"https://www.youtube.com/watch?v={vid}" if vid else ""
            entries.append({
                "id": vid, "url": vurl,
                "title": e.get("title") or vid or "Unknown",
                "duration": e.get("duration"),
                "duration_string": format_duration(e.get("duration")),
                "thumbnail": (e.get("thumbnails") or [{}])[-1].get("url") if e.get("thumbnails") else "",
            })
        thumbs = flat.get("thumbnails") or []
        return {
            "is_playlist": True,
            "playlist": {"id": flat.get("id") or "", "url": flat.get("webpage_url") or pl_url,
                         "title": flat.get("title") or "Playlist",
                         "count": flat.get("playlist_count") or len(entries)},
            "playlist_title": flat.get("title") or "Playlist",
            "playlist_count": flat.get("playlist_count") or len(entries),
            "entries": entries,
            "title": flat.get("title") or "Playlist",
            "channel": flat.get("uploader") or flat.get("channel") or "",
            "thumbnail": thumbs[-1].get("url") if thumbs else (entries[0].get("thumbnail") if entries else ""),
            "webpage_url": flat.get("webpage_url") or url,
            "quality_options": [{"value": "best", "label": "Best available", "available": True},
                                *[{"value": v, "label": f"{v}p", "available": True}
                                  for v in ("2160", "1440", "1080", "720", "480")],
                                ],
        }

    # Single video. IMPORTANT: strip any &list=/&index= params first — probing a
    # watch+list URL confuses yt-dlp's flat extractor and yields playlist data
    # for a "video", which previously surfaced as "Video unavailable".
    video_url = canonical_video_url(url) or url
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                               "js_runtimes": dict(YTDL_JS_RUNTIMES)}) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=friendly_yt_error(exc))
    if info is None:
        raise HTTPException(status_code=400, detail="Video unavailable.")
    # A playlist page can slip through as a dict with entries but no formats;
    # treat that as "not a single video".
    if info.get("_type") == "playlist":
        raise HTTPException(status_code=400, detail="That URL is a playlist. Open the playlist URL or pick a video from it.")
    thumbs = info.get("thumbnails") or []
    playlist = None
    if parts["list_id"]:
        pl_url = canonical_playlist_url(url)
        if pl_url:
            playlist = _probe_playlist_summary(pl_url)
    return {
        "is_playlist": False,
        "id": info.get("id"),
        "title": info.get("title") or "Unknown title",
        "channel": info.get("uploader") or info.get("channel") or "",
        "duration": info.get("duration"),
        "duration_string": format_duration(info.get("duration")),
        "thumbnail": info.get("thumbnail") or (thumbs[-1].get("url") if thumbs else ""),
        "webpage_url": info.get("webpage_url") or video_url,
        "quality_options": available_quality_options(info),
        "playlist": playlist,
    }


# ---------- download ----------
@app.post("/download", dependencies=[Depends(require_auth)])
async def start_download(body: DownloadRequest):
    url = (body.url or "").strip()
    if not url or ("youtube.com" not in url and "youtu.be" not in url):
        raise HTTPException(status_code=400, detail="Invalid URL.")
    if not check_ffmpeg():
        raise HTTPException(status_code=500, detail=FFMPEG_INSTALL_MSG)
    quality = (body.quality or "best").lower()
    if quality not in ("best", "2160", "1440", "1080", "720", "480"):
        raise HTTPException(status_code=400, detail="Invalid quality.")
    container = (body.container or "mp4").lower()
    if container not in ("mp4", "mkv"):
        raise HTTPException(status_code=400, detail="Container must be mp4 or mkv.")
    playlist_url = (body.playlist_url or "").strip() or None
    if bool(body.download_playlist):
        # Resolve which playlist to expand: explicit URL wins, else the list
        # param of the given URL. A bare single video is not a playlist.
        if not playlist_url:
            playlist_url = canonical_playlist_url(url)
        if not playlist_url:
            raise HTTPException(status_code=400, detail="That URL is not a playlist. Use a playlist URL or a video URL containing &list=....")
    else:
        # Single-video scope: strip &list=/&index= so yt-dlp sees a clean video URL.
        url = canonical_video_url(url) or url
    job = await manager.create_job(
        url=url, quality=quality, container=container,
        audio_only=bool(body.audio_only),
        audio_format=(body.audio_format or "mp3").lower(),
        audio_bitrate=str(body.audio_bitrate or "192"),
        download_playlist=bool(body.download_playlist),
        playlist_url=playlist_url,
    )
    return JSONResponse({"job_id": job["job_id"], "job": job})


@app.get("/jobs", dependencies=[Depends(require_auth)])
def list_jobs(active_only: bool = False):
    return {"jobs": manager.list_jobs(active_only=active_only),
            "active": manager.active_count()}


@app.get("/jobs/{job_id}", dependencies=[Depends(require_auth)])
def job_status(job_id: str):
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown download id.")
    return DownloadManager._public_job(job)


@app.post("/cancel/{job_id}", dependencies=[Depends(require_auth)])
def cancel(job_id: str):
    if not manager.cancel_job(job_id):
        job = manager.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Unknown download id.")
        return {"ok": True, "status": job["status"]}
    return {"ok": True, "status": "cancelled"}


@app.get("/progress/{job_id}")
async def progress_sse(job_id: str, request: Request, token: str | None = Query(default=None)):
    # Auth manually because EventSource can't send Authorization headers
    expected = current_token()
    if not expected or (token or "").strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid token (use ?token=... for SSE).")
    if not manager.get_job(job_id):
        raise HTTPException(status_code=404, detail="Unknown download id.")

    async def gen():
        last = ""
        while True:
            if await request.is_disconnected():
                break
            job = manager.get_job(job_id)
            if not job:
                break
            payload = json.dumps(DownloadManager._public_job(job))
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if job["status"] in ("completed", "error", "cancelled"):
                # Send one final event then close
                await asyncio.sleep(0.3)
                break
            await asyncio.sleep(0.7)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- history ----------
@app.get("/history", dependencies=[Depends(require_auth)])
def history(limit: int = 100):
    items = dbmod.list_entries(DB_PATH, limit=max(1, min(500, limit)))
    # Attach file-exists flag
    for it in items:
        try:
            it["file_exists"] = bool(it.get("filepath")) and Path(str(it["filepath"])).exists()
        except Exception:
            it["file_exists"] = False
    return {"history": items}


@app.delete("/history/{row_id}", dependencies=[Depends(require_auth)])
def delete_history(row_id: int, delete_file: bool = False):
    entry = dbmod.get_entry(DB_PATH, row_id)
    if not entry:
        raise HTTPException(status_code=404, detail="History entry not found.")
    if delete_file and entry.get("filepath"):
        try:
            Path(str(entry["filepath"])).unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception:
            pass
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("DELETE FROM downloads WHERE id=?", (row_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.post("/history/{row_id}/reveal", dependencies=[Depends(require_auth)])
def reveal_file(row_id: int):
    import platform
    entry = dbmod.get_entry(DB_PATH, row_id)
    if not entry or not entry.get("filepath"):
        raise HTTPException(status_code=404, detail="File path unknown.")
    p = Path(str(entry["filepath"]))
    folder = str(p.parent if p.parent.exists() else Path(cfg["download_dir"]).expanduser())
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.Popen(["explorer", "/select,", str(p) if p.exists() else folder])
        elif system == "Darwin":
            subprocess.Popen(["open", "-R", str(p)] if p.exists() else ["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not open folder: {exc}")
    return {"ok": True, "folder": folder}


@app.post("/history/{row_id}/redownload", dependencies=[Depends(require_auth)])
async def redownload(row_id: int):
    entry = dbmod.get_entry(DB_PATH, row_id)
    if not entry or not entry.get("url"):
        raise HTTPException(status_code=404, detail="Entry has no URL.")
    q = entry.get("quality") or "best"
    audio_only = bool(entry.get("audio_only"))
    # quality for audio entries is stored like "audio-mp3-192"
    quality, audio_format, audio_bitrate = "best", "mp3", "192"
    if isinstance(q, str) and q.startswith("audio-"):
        audio_only = True
        try:
            _, audio_format, audio_bitrate = q.split("-", 2)
        except ValueError:
            pass
    else:
        quality = q
    job = await manager.create_job(
        url=str(entry["url"]), quality=quality,
        container=str(entry.get("container") or "mp4"),
        audio_only=audio_only, audio_format=audio_format,
        audio_bitrate=audio_bitrate, download_playlist=False)
    return {"job_id": job["job_id"], "job": job}


# ---------- settings / maintenance ----------
@app.get("/settings", dependencies=[Depends(require_auth)])
def get_settings():
    return {"download_dir": str(cfg.get("download_dir")),
            "max_concurrent": int(cfg.get("max_concurrent", 2)),
            "port": int(cfg.get("port", 8765))}


@app.post("/settings", dependencies=[Depends(require_auth)])
def update_settings(body: SettingsRequest):
    if body.download_dir:
        p = Path(body.download_dir).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Cannot use that folder: {exc}")
        cfg["download_dir"] = str(p)
        manager.cfg["download_dir"] = str(p)
    if body.max_concurrent is not None:
        manager.set_max_concurrent(int(body.max_concurrent))
        cfg["max_concurrent"] = int(manager.cfg["max_concurrent"])
    save_config(cfg)
    return {"ok": True, "download_dir": str(cfg.get("download_dir")),
            "max_concurrent": int(cfg.get("max_concurrent", 2))}


@app.post("/update-ytdlp", dependencies=[Depends(require_auth)])
def update_ytdlp():
    """Upgrade yt-dlp via pip. Also documented as CLI: python -m pip install -U yt-dlp"""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
            capture_output=True, text=True, timeout=180)
        ver = ytdlp_version()
        if proc.returncode != 0:
            raise HTTPException(status_code=500,
                                detail=f"yt-dlp update failed: {(proc.stderr or proc.stdout)[-1000:]}")
        return {"ok": True, "output_tail": (proc.stdout or "")[-1000:],
                "ytdlp_version": ver,
                "hint": "If the version looks old, restart the companion server."}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"yt-dlp update failed: {exc}")


@app.on_event("startup")
def _startup():
    print(f"[companion] v{VERSION} starting. Bound to 127.0.0.1 only.", flush=True)
    print(f"[companion] Downloads: {cfg.get('download_dir')}", flush=True)
    print(f"[companion] API token: {current_token()}", flush=True)
    print("[companion] Paste this token once into the extension Options page.", flush=True)
    if not check_ffmpeg():
        print(f"[companion] WARNING:\n{FFMPEG_INSTALL_MSG}", flush=True)
    else:
        print(f"[companion] {ffmpeg_version()}", flush=True)


@app.exception_handler(HTTPException)
async def _http_exc(_: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
