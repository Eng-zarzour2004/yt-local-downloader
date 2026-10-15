"""Download job manager built on yt-dlp (blocking) executed in threads."""
from __future__ import annotations

import asyncio
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import db as dbmod
from .utils import (
    YTDL_JS_RUNTIMES,
    build_download_opts,
    canonical_playlist_url,
    canonical_video_url,
    friendly_yt_error,
    sanitize_filename,
)


class DownloadCancelled(Exception):
    pass


def short_id() -> str:
    return uuid.uuid4().hex[:12]


def resolve_final_file(download_dir: Path, safe_title: str, label: str,
                       final_ext: str, candidate: str = "") -> str:
    """Pick the real output file.

    NOTE: never use ``Path.glob`` with the ``"<title> [<res>].*"`` pattern —
    glob treats ``[480p]`` as a character class and won't match the literal
    filename. Compare names directly instead.
    """
    expected = download_dir / f"{safe_title} [{label}].{final_ext}"
    if expected.exists():
        return str(expected)
    prefix = f"{safe_title} [{label}]."
    cands: list[Path] = []
    try:
        for x in download_dir.iterdir():
            if not (x.is_file() and x.name.startswith(prefix)):
                continue
            if x.suffix in (".part", ".ytdl", ".temp", ".tmp"):
                continue
            if re.match(r".*\.f\d+\.[a-z0-9]+$", x.name):  # yt-dlp stream-part temp file
                continue
            cands.append(x)
    except OSError:
        pass
    if cands:
        # Prefer the exact final container, else newest.
        exact = [c for c in cands if c.suffix.lower() == "." + final_ext]
        pool = exact or cands
        pool.sort(key=lambda p: p.stat().st_mtime)
        return str(pool[-1])
    return candidate


class DownloadManager:
    def __init__(self, cfg: dict, db_path: Path):
        self.cfg = cfg
        self.db_path = db_path
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.sem = asyncio.Semaphore(int(cfg.get("max_concurrent", 2) or 2))

    def set_max_concurrent(self, n: int) -> None:
        n = max(1, min(5, int(n or 2)))
        self.cfg["max_concurrent"] = n
        self.sem = asyncio.Semaphore(n)

    # ---- job queries ----
    def get_job(self, job_id: str) -> dict | None:
        with self.lock:
            return self.jobs.get(job_id)

    def list_jobs(self, active_only: bool = False) -> list[dict]:
        with self.lock:
            jobs = list(self.jobs.values())
        if active_only:
            jobs = [j for j in jobs if j["status"] in ("queued", "downloading", "merging")]
        return [self._public_job(j) for j in jobs]

    def active_count(self) -> int:
        with self.lock:
            return sum(1 for j in self.jobs.values()
                       if j["status"] in ("queued", "downloading", "merging"))

    @staticmethod
    def _public_job(j: dict) -> dict:
        return {
            "job_id": j["job_id"],
            "url": j["url"],
            "quality": j["quality"],
            "container": j["container"],
            "audio_only": j["audio_only"],
            "status": j["status"],
            "percent": round(j.get("percent", 0.0), 1),
            "speed_str": j.get("speed_str", ""),
            "eta_str": j.get("eta_str", ""),
            "downloaded_bytes": j.get("downloaded_bytes", 0),
            "total_bytes": j.get("total_bytes", 0),
            "current_title": j.get("current_title", ""),
            "current_index": j.get("current_index", 0),
            "total_items": j.get("total_items", 1),
            "error": j.get("error", ""),
            "filepath": j.get("filepath", ""),
            "items": [
                {"index": it["index"], "url": it["url"], "title": it.get("title", ""),
                 "status": it.get("status", "queued"), "percent": round(it.get("percent", 0.0), 1),
                 "filepath": it.get("filepath", ""), "error": it.get("error", "")}
                for it in j.get("items", [])
            ],
        }

    def cancel_job(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return False
            if job["status"] in ("completed", "error", "cancelled"):
                return False
            job["cancel_requested"] = True
            # Mark queued items cancelled so waiting loop exits fast
            return True

    # ---- create + run ----
    async def create_job(self, url: str, quality: str = "best", container: str = "mp4",
                         audio_only: bool = False, audio_format: str = "mp3",
                         audio_bitrate: str = "192", download_playlist: bool = False,
                         playlist_url: str | None = None) -> dict:
        job_id = short_id()
        job: dict[str, Any] = {
            "job_id": job_id,
            "url": url,
            "quality": quality,
            "container": container,
            "audio_only": audio_only,
            "audio_format": audio_format,
            "audio_bitrate": audio_bitrate,
            "download_playlist": bool(download_playlist),
            "playlist_url": playlist_url or None,
            "status": "queued",
            "percent": 0.0,
            "speed_str": "",
            "eta_str": "",
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "current_title": "",
            "current_index": 0,
            "total_items": 1,
            "error": "",
            "filepath": "",
            "items": [],
            "cancel_requested": False,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        with self.lock:
            self.jobs[job_id] = job
        # Fire-and-forget runner
        asyncio.create_task(self._run_job(job_id))
        return self._public_job(job)

    async def _run_job(self, job_id: str) -> None:
        async with self.sem:
            with self.lock:
                job = self.jobs.get(job_id)
                if not job or job["status"] != "queued":
                    return
                if job["cancel_requested"]:
                    job["status"] = "cancelled"
                    return
                job["status"] = "downloading"
            try:
                await asyncio.to_thread(self._download_blocking, job_id)
            except DownloadCancelled:
                with self.lock:
                    job = self.jobs.get(job_id)
                    if job:
                        job["status"] = "cancelled"
                        for it in job["items"]:
                            if it["status"] in ("queued", "downloading"):
                                it["status"] = "cancelled"
            except Exception as exc:  # noqa: BLE001
                with self.lock:
                    job = self.jobs.get(job_id)
                    if job:
                        job["status"] = "error"
                        job["error"] = friendly_yt_error(exc)

    # ---- blocking worker (runs in thread) ----
    def _download_blocking(self, job_id: str) -> None:
        import yt_dlp  # local import so version errors surface here

        with self.lock:
            job = self.jobs[job_id]
        url = job["url"]
        download_playlist = job["download_playlist"]
        # Expand whole-playlist scope via the canonical playlist URL, never via a
        # watch+list URL (yt-dlp's flat extractor confuses the two).
        playlist_probe_url = job.get("playlist_url") or canonical_playlist_url(url)
        # Single-video scope: always probe a clean canonical video URL.
        single_url = canonical_video_url(url) or url

        # 1) Expand playlist (flat, fast) to build item queue.
        # Whole-playlist scope probes the canonical playlist URL; single-video
        # scope probes the canonical video URL. Never probe a watch+list URL.
        probe_url = playlist_probe_url if (download_playlist and playlist_probe_url) else single_url
        entries: list[dict] = []
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                   "js_runtimes": dict(YTDL_JS_RUNTIMES),
                                   "extract_flat": True, "noplaylist": False}) as ydl:
                flat = ydl.extract_info(probe_url, download=False)
        except Exception as exc:
            raise RuntimeError(friendly_yt_error(exc)) from exc

        if flat is None:
            raise RuntimeError("Could not read that URL (empty response from YouTube).")

        if download_playlist:
            if flat.get("_type") != "playlist":
                raise RuntimeError("That URL is not a playlist (it may be private or deleted).")
            for i, e in enumerate(flat.get("entries") or []):
                if e is None:
                    continue
                vid_id = e.get("id") or ""
                vurl = e.get("url") or ""
                if vurl.startswith("/"):
                    vurl = "https://www.youtube.com" + vurl
                elif not vurl.startswith("http"):
                    vurl = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else url
                entries.append({"index": i, "url": vurl,
                                "title": e.get("title") or f"Item {i+1}",
                                "status": "queued", "percent": 0.0,
                                "filepath": "", "error": "", "row_id": None})
            if not entries:
                raise RuntimeError("Playlist appears empty or private.")
        else:
            # Single video.
            entries.append({"index": 0, "url": flat.get("webpage_url") or single_url,
                            "title": flat.get("title") or "video",
                            "status": "queued", "percent": 0.0,
                            "filepath": "", "error": "", "row_id": None})

        with self.lock:
            job["items"] = entries
            job["total_items"] = len(entries)

        # 2) Download each item sequentially
        download_dir = Path(self.cfg["download_dir"]).expanduser()
        download_dir.mkdir(parents=True, exist_ok=True)

        for item in entries:
            with self.lock:
                if job["cancel_requested"]:
                    raise DownloadCancelled()
                job["current_index"] = item["index"]
                job["current_title"] = item["title"]
                item["status"] = "downloading"
            row_id = dbmod.add_entry(self.db_path, {
                "job_id": job_id, "item_id": str(item["index"]),
                "url": item["url"], "title": item["title"],
                "quality": job["quality"] if not job["audio_only"] else f"audio-{job['audio_format']}-{job['audio_bitrate']}",
                "container": job["container"], "audio_only": job["audio_only"],
                "status": "downloading",
            })
            item["row_id"] = row_id
            try:
                filepath = self._download_single(ydl_module=yt_dlp, job=job, item=item,
                                                 download_dir=download_dir)
                item["status"] = "completed"
                item["percent"] = 100.0
                item["filepath"] = filepath
                with self.lock:
                    job["filepath"] = filepath  # last file (single-video case = the file)
                try:
                    size = Path(filepath).stat().st_size if filepath and Path(filepath).exists() else 0
                except Exception:
                    size = 0
                dbmod.update_entry(self.db_path, row_id, {
                    "status": "completed", "filepath": filepath,
                    "title": item.get("title") or job.get("current_title") or "",
                    "filesize": size,
                    "completed_at": dbmod.now_iso(),
                })
            except DownloadCancelled:
                item["status"] = "cancelled"
                dbmod.update_entry(self.db_path, row_id, {"status": "cancelled",
                                                          "completed_at": dbmod.now_iso()})
                raise
            except Exception as exc:  # noqa: BLE001
                err = friendly_yt_error(exc)
                item["status"] = "error"
                item["error"] = err
                dbmod.update_entry(self.db_path, row_id, {"status": "error", "error": err,
                                                          "completed_at": dbmod.now_iso()})
                # Continue with next playlist item instead of aborting whole job
                continue
            finally:
                with self.lock:
                    done = sum(1 for it in entries if it["status"] in ("completed", "error", "cancelled"))
                    job["percent"] = (done / max(1, len(entries))) * 100.0

        with self.lock:
            if job["cancel_requested"]:
                job["status"] = "cancelled"
                return
            errs = [it for it in entries if it["status"] == "error"]
            if len(errs) == len(entries):
                job["status"] = "error"
                job["error"] = errs[0].get("error", "Download failed.") if errs else "Download failed."
            else:
                job["status"] = "completed"
                job["percent"] = 100.0
                job["speed_str"] = ""
                job["eta_str"] = ""

    def _download_single(self, ydl_module, job: dict, item: dict, download_dir: Path) -> str:
        fmt, merge_fmt, postprocessors, final_ext = build_download_opts(
            job["quality"], job["container"], job["audio_only"],
            job["audio_format"], job["audio_bitrate"])

        # Pre-fetch title for a clean filename: {title} [{resolution}].{ext}
        try:
            with ydl_module.YoutubeDL({"quiet": True, "no_warnings": True,
                                       "js_runtimes": dict(YTDL_JS_RUNTIMES)}) as probe:
                meta = probe.extract_info(item["url"], download=False)
                if meta:
                    item["title"] = meta.get("title") or item["title"]
                    with self.lock:
                        job["current_title"] = item["title"]
        except Exception:
            pass

        if job["audio_only"]:
            label = f"{job['audio_format']}-{job['audio_bitrate']}"
        else:
            label = job["quality"] if job["quality"] == "best" else f"{job['quality']}p"
        safe_title = sanitize_filename(item["title"])
        outtmpl = str(download_dir / f"{safe_title} [{label}].%(ext)s")

        result_path: dict[str, str] = {}

        def hook(d: dict) -> None:
            with self.lock:
                if job["cancel_requested"]:
                    raise DownloadCancelled()
            status = d.get("status")
            if status == "downloading":
                dl = d.get("downloaded_bytes") or 0
                tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                with self.lock:
                    job["downloaded_bytes"] = dl
                    job["total_bytes"] = tot
                    job["speed_str"] = self._fmt_speed(d.get("speed"))
                    job["eta_str"] = self._fmt_eta(d.get("eta"))
                    if tot:
                        pct = dl / tot * 100.0
                        # Blend with playlist position
                        base = (item["index"] / max(1, len(job["items"]))) * 100.0
                        job["percent"] = base + pct / max(1, len(job["items"]))
                        item["percent"] = pct
                    fn = d.get("filename") or d.get("tmpfilename") or ""
                    if fn:
                        result_path["file"] = fn
            elif status == "finished":
                with self.lock:
                    job["status"] = "merging"
                    job["speed_str"] = "merging…"
                    fn = d.get("filename") or ""
                    if fn:
                        result_path["file"] = fn

        params: dict = {
            "quiet": True,
            "no_warnings": True,
            "js_runtimes": dict(YTDL_JS_RUNTIMES),
            "format": fmt,
            "outtmpl": outtmpl,
            "noplaylist": True,
            "progress_hooks": [hook],
            "postprocessors": list(postprocessors),
        }
        if merge_fmt:
            # Merge separate video+audio streams into one file (no re-encode when
            # codecs are container-compatible; ffmpeg handles it automatically).
            params["merge_output_format"] = merge_fmt

        with ydl_module.YoutubeDL(params) as ydl:
            try:
                ydl.download([item["url"]])
            except DownloadCancelled:
                # Remove partial fragments so cancelled downloads don't litter the folder.
                prefix = f"{safe_title} [{label}]."
                try:
                    for x in download_dir.iterdir():
                        if (x.is_file() and x.name.startswith(prefix)
                                and (x.suffix in (".part", ".ytdl", ".temp", ".tmp")
                                     or re.match(r".*\.f\d+\.[a-z0-9]+(\.part)?$", x.name))):
                            x.unlink(missing_ok=True)
                except OSError:
                    pass
                raise

        # Resolve final file: yt-dlp may change ext during merge/extract.
        candidate = result_path.get("file", "")
        return resolve_final_file(download_dir, safe_title, label, final_ext, candidate)

    @staticmethod
    def _fmt_speed(speed) -> str:
        if not speed:
            return ""
        try:
            s = float(speed)
        except Exception:
            return ""
        for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
            if s < 1024 or unit == "GB/s":
                return f"{s:.1f} {unit}"
            s /= 1024
        return ""

    @staticmethod
    def _fmt_eta(eta) -> str:
        if eta is None:
            return ""
        try:
            e = int(eta)
        except Exception:
            return ""
        if e < 60:
            return f"{e}s left"
        m, s = divmod(e, 60)
        if m < 60:
            return f"{m}m {s}s left"
        h, m = divmod(m, 60)
        return f"{h}h {m}m left"
