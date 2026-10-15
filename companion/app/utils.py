"""Small helpers: filenames, ffmpeg check, format strings, errors."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse
import shutil
import subprocess

ILLEGAL_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# JS runtimes for YouTube signature solving. Deno is yt-dlp's default; Node is
# added because it ships with many dev machines (verified on PATH here) and
# unlocks formats that otherwise show as missing. Runtimes that aren't
# installed are skipped by yt-dlp with a warning, so this is safe everywhere.
YTDL_JS_RUNTIMES = {"deno": {}, "node": {}}
FFMPEG_INSTALL_MSG = (
    "ffmpeg not found on PATH. Install it first:\n"
    "  Windows: winget install Gyan.FFmpeg  (or choco install ffmpeg) then restart terminal\n"
    "  macOS:   brew install ffmpeg\n"
    "  Linux:   sudo apt install ffmpeg  (or sudo dnf install ffmpeg)\n"
    "Then restart the companion server."
)


def sanitize_filename(name: str, max_len: int = 150) -> str:
    name = (name or "video").strip()
    name = ILLEGAL_CHARS_RE.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.strip("._ ")
    if len(name) > max_len:
        name = name[:max_len].rstrip("._ ")
    return name or "video"


def format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return ""
    try:
        s = int(seconds)
    except Exception:
        return ""
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def ffmpeg_version() -> str:
    try:
        out = subprocess.check_output(["ffmpeg", "-version"], text=True, timeout=5)
        return out.splitlines()[0][:120] if out else "ffmpeg"
    except Exception:
        return ""


def build_download_opts(quality: str, container: str, audio_only: bool,
                        audio_format: str, audio_bitrate: str):
    """Return (format_string, merge_format, postprocessors, final_ext)."""
    container = (container or "mp4").lower()
    if container not in ("mp4", "mkv"):
        container = "mp4"
    audio_format = (audio_format or "mp3").lower()
    audio_bitrate = str(audio_bitrate or "192")

    if audio_only:
        fmt = "bestaudio/best"
        if audio_format == "m4a":
            pp = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]
            ext = "m4a"
        else:
            pp = [{"key": "FFmpegExtractAudio",
                   "preferredcodec": "mp3",
                   "preferredquality": audio_bitrate}]
            ext = "mp3"
        return fmt, None, pp, ext

    q = (quality or "best").lower()
    height_map = {"2160": 2160, "1440": 1440, "1080": 1080, "720": 720, "480": 480}
    if q in height_map:
        h = height_map[q]
        fmt = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
    else:  # best
        fmt = "bestvideo+bestaudio/best"
    return fmt, container, [], container


def friendly_yt_error(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "private video" in low:
        return "This video is private."
    if "age" in low and ("confirm" in low or "restricted" in low):
        return "Age-restricted video. Sign-in / cookies required; yt-dlp cannot access it anonymously."
    if "unavailable" in low or "removed" in low or "deleted" in low:
        return "Video is unavailable, deleted, or removed."
    if "not found" in low or "404" in low:
        return "Video not found. Check the URL."
    if "timed out" in low or "timeout" in low or "network" in low or "connection" in low:
        return f"Network failure while contacting YouTube: {msg[:300]}"
    if "ffmpeg" in low:
        return f"ffmpeg error: {msg[:300]}"
    if "sign in" in low or "login required" in low:
        return "YouTube requires login for this video (private/age-restricted)."
    return f"Download failed: {msg[:500]}"


def parse_available_heights(info: dict) -> list[int]:
    """Inspect yt-dlp formats list and return sorted available video heights."""
    heights: set[int] = set()
    for f in (info.get("formats") or []):
        h = f.get("height")
        vcodec = f.get("vcodec") or ""
        if h and vcodec != "none":
            try:
                heights.add(int(h))
            except Exception:
                pass
    return sorted(heights)


def available_quality_options(info: dict) -> list[dict]:
    """Only return quality options that actually exist for this video."""
    heights = parse_available_heights(info)
    max_h = max(heights) if heights else 0
    candidates = [2160, 1440, 1080, 720, 480]
    opts = [{"value": "best", "label": "Best available", "available": True}]
    for c in candidates:
        # Available if there is any stream >= c*0.9 or max_h >= c (approx).
        # If we have no format data, mark all as available (fallback).
        if not heights:
            avail = True
        else:
            avail = any(h >= int(c * 0.9) for h in heights) or max_h >= c
            # Also allow lower qualities if a higher stream exists (yt-dlp can downscale? no -
            # but YouTube almost always has 360/720; be permissive for <= max_h).
            if max_h >= c:
                avail = True
        opts.append({"value": str(c), "label": f"{c}p", "available": avail})
    return opts


def split_youtube_url(url: str) -> dict:
    """Split a YouTube URL into video id / playlist id parts.

    Handles watch?v= (+&list=), youtu.be, /shorts/, /embed/ and /playlist.
    A pasted id longer than 11 chars is trimmed (matches yt-dlp behaviour).
    """
    out = {"video_id": None, "list_id": None, "is_playlist_url": False}
    try:
        u = urlparse(url or "")
    except Exception:
        return out
    host = (u.hostname or "").lower()
    host = re.sub(r"^(www\.|m\.)", "", host)
    try:
        q = parse_qs(u.query or "")
    except Exception:
        q = {}
    lst = (q.get("list") or [None])[0]
    if lst:
        out["list_id"] = lst
    vid: str | None = None
    if host == "youtu.be":
        segs = [s for s in (u.path or "").split("/") if s]
        vid = segs[0] if segs else None
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        p = u.path or ""
        if p == "/playlist":
            out["is_playlist_url"] = bool(lst)
        elif p.startswith("/shorts/"):
            segs = [s for s in p.split("/") if s]
            vid = segs[1] if len(segs) > 1 else None
        elif p.startswith("/embed/") or p.startswith("/live/"):
            segs = [s for s in p.split("/") if s]
            vid = segs[1] if len(segs) > 1 else None
        elif p == "/watch":
            vid = (q.get("v") or [None])[0]
    if vid and len(vid) > 11:
        vid = vid[:11]
    out["video_id"] = vid or None
    return out


def canonical_video_url(url: str) -> str | None:
    parts = split_youtube_url(url)
    if parts["video_id"]:
        return f"https://www.youtube.com/watch?v={parts['video_id']}"
    return None


def canonical_playlist_url(url_or_id: str) -> str | None:
    s = (url_or_id or "").strip()
    if s.startswith("http"):
        parts = split_youtube_url(s)
        lid = parts["list_id"]
    else:
        lid = s or None
    if lid:
        return f"https://www.youtube.com/playlist?list={lid}"
    return None
