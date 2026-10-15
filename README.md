# YT Local Downloader — Extension + Companion (yt-dlp + ffmpeg)

Download YouTube videos in high quality to your computer. Two parts:

- **`extension/`** — Chrome / Edge / Brave MV3 extension (plain HTML/CSS/vanilla JS, no build step). Firefox compatible (bonus).
- **`companion/`** — local Python 3.10+ FastAPI server on `127.0.0.1:8765` that runs yt-dlp + ffmpeg. Browser extensions can't run native binaries, so this is the engine.

> **Personal sideloaded use only — not for publishing to the Chrome Web Store** (which prohibits YouTube-download extensions).
> Only download content you own, that is Creative Commons / public domain, or that you have explicit permission to download.
> **You are responsible for complying with YouTube's Terms of Service and copyright law.**

---

## 1. How it works

```
YouTube page → [Download button / popup] → http://127.0.0.1:8765 → yt-dlp + ffmpeg → ~/Downloads/YTDownloader
                                              (shared-secret token + strict CORS + SSE progress)
```

- `bestvideo+bestaudio` strategy: 1080p+ comes as separate streams, merged with ffmpeg into one MP4/MKV named `{title} [{resolution}].{ext}` (sanitized).
- Real-time progress over Server-Sent Events (`/progress/{id}`), with polling fallback so progress survives popup close (service worker cache).
- History in SQLite (`companion/history.db`).

---

## 2. Prerequisites

| OS | Python | ffmpeg |
|---|---|---|
| Windows 10/11 | `winget install Python.Python.3.12` (or from python.org, tick "Add to PATH") | `winget install Gyan.FFmpeg` then **reopen terminal** |
| macOS | `brew install python` (or python.org) | `brew install ffmpeg` |
| Ubuntu/Debian | `sudo apt update && sudo apt install python3 python3-venv ffmpeg` | included |
| Fedora | `sudo dnf install python3 ffmpeg` | included |

Verify:

```bash
python --version    # 3.10+
ffmpeg -version     # should print a version
```

---

## 3. Start the companion

### Windows

```bat
cd companion
run.bat
```

`run.bat` creates `.venv`, installs `requirements.txt`, and starts the server. Keep the window open. First run prints something like:

```
[companion] Downloads: C:\Users\you\Downloads\YTDownloader
[companion] API token: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
[companion] Paste this token once into the extension Options page.
Starting companion on http://127.0.0.1:8765 ...
```

Copy that token → extension Options page.

### macOS / Linux

```bash
cd companion
chmod +x run.sh
./run.sh
```

Manual equivalent:

```bash
cd companion
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python run.py
```

Update yt-dlp anytime (button in extension Options calls `/update-ytdlp`, or CLI):

```bash
# inside companion/.venv, with venv activated:
python -m pip install -U yt-dlp
```

### Auto-start at login (optional)

- **Windows:** Win+R → `shell:startup` → create shortcut to `companion\run.bat` (or use Task Scheduler → trigger "At log on").
- **macOS:** System Settings → General → Login Items → add a small app/Automator script running `companion/run.sh`, or a `launchd` plist calling `/path/to/companion/.venv/bin/python /path/to/companion/run.py`.
- **Linux:** add `companion/run.sh` to Startup Applications, or a systemd user unit:
  `~/.config/systemd/user/ytdl-companion.service` → `ExecStart=/path/to/companion/.venv/bin/python /path/to/companion/run.py`, then `systemctl --user enable --now ytdl-companion`.

---

## 4. Load the extension

### Chrome / Edge / Brave

1. Go to `chrome://extensions` (Edge: `edge://extensions`, Brave: `brave://extensions`).
2. Enable **Developer mode** (top right).
3. **Load unpacked** → select the `extension/` folder.
4. Open extension **Options**, set:
   - Companion URL: `http://127.0.0.1:8765`
   - API token: paste from companion console
   - defaults (quality/container/concurrency)
5. Click **Test connection** — want green. If red, companion isn't running or port/token is wrong.

### Firefox (`about:debugging`)

1. Go to `about:debugging#/runtime/this-firefox`.
2. **Load Temporary Add-on…** → pick `extension/manifest.json`.
3. Note: temporary add-ons unload on browser restart (re-load the same way); `browser_specific_settings.gecko.id` is already set.

---

## 5. Main flow test (do this once)
1. Start companion (`run.bat` / `run.sh`), confirm `http://127.0.0.1:8765/health` returns `{"status":"ok",...}`.
2. Open any public YouTube video → you should see a **Download** pill next to Like/Share (content script). Click it, or click the extension icon.
3. Popup auto-fills the URL → click **Get** if needed → preview card (thumbnail/title/channel/duration) appears.
4. Choose **1080p + MP4**, click **Download** → progress bar with %, speed, ETA + **Cancel**.
5. Close and reopen the popup mid-download — progress resumes (service worker + `GET /jobs/{id}`).
6. When done: badge clears, desktop notification fires, merged MP4 named `Title [1080p].mp4` is in your downloads folder, and the **History** tab shows it (re-download / open folder / delete).

Playlist test: open a `&list=` URL → choose **Whole playlist** → queue with per-item progress.

---

## Daily use

### On Windows

1. Double-click `companion\run.bat` (a terminal opens — leave it open; first run already installed everything).
2. Open Chrome/Edge/Brave. The extension stays installed from the one-time setup.
3. Open a YouTube video → click **Download** next to Like/Share, or click the extension icon → pick quality → **Download**.
4. Find files in `Downloads\YTDownloader` (or press **Open folder** in the History tab).
5. When done, close the companion terminal.

### On Linux

1. Open a terminal:
   ```bash
   cd yt-downloader/companion
   ./run.sh
   ```
   Leave it running.
2. Open Chrome/Chromium. The extension stays loaded from the one-time setup (Firefox temporary add-ons must be re-loaded after each browser restart via `about:debugging`).
3. Same as Windows: YouTube page → **Download** → quality → **Download**.
4. Files land in `~/Downloads/YTDownloader/`.
5. When done, `Ctrl+C` the terminal.

> The companion must be running whenever you download. The extension only stores the server URL + token — no video data passes through anything but your own machine.

---

---

## 6. API reference (companion)

All except `GET /health` require `Authorization: Bearer <token>` (SSE uses `?token=` since EventSource can't set headers).

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | public: version, ffmpeg, yt-dlp, active count |
| POST | `/info` `{url}` | metadata + real format options + playlist entries |
| POST | `/download` | start job `{url, quality, container, audio_only, audio_format, audio_bitrate, download_playlist}` → `{job_id}` |
| GET | `/jobs?active_only=` | list jobs (badge + queue) |
| GET | `/jobs/{id}` | poll single job (popup-reopen fallback) |
| GET | `/progress/{id}?token=` | SSE stream |
| POST | `/cancel/{id}` | cancel |
| GET | `/history?limit=` | SQLite history |
| DELETE | `/history/{id}?delete_file=true` | delete record (+ file) |
| POST | `/history/{id}/reveal` | open containing folder |
| POST | `/history/{id}/redownload` | new job from history |
| GET/POST | `/settings` | download_dir, max_concurrent |
| POST | `/update-ytdlp` | `pip install -U yt-dlp` |

Files: `{title} [{resolution}].{ext}` in the configured folder, illegal chars → `_`.

Clear errors reach the UI: invalid URL, private/age-restricted/unavailable, network failure, ffmpeg missing, companion not running (fetch failure in popup).

---

## 7. Folder structure

```
yt-downloader/
  README.md
  extension/
    manifest.json
    common/api.js
    popup/popup.html popup.css popup.js
    content/content.js content.css
    background/background.js
    options/options.html options.css options.js
    icons/icon16.png icon48.png icon128.png
  companion/
    app/__init__.py main.py config.py downloader.py db.py utils.py
    requirements.txt (pinned)
    run.py run.bat run.sh
    config.example.json
```

Permissions requested (minimum): `activeTab`, `storage`, `notifications`, `alarms` (badge polling) + host access only to `youtube.com`/`youtu.be` and `127.0.0.1`/`localhost`.

## 8. Troubleshooting

- **Popup: "Cannot reach companion"** → companion window closed? Wrong port? `curl http://127.0.0.1:8765/health`.
- **401 Invalid token** → copy the exact token from companion startup log into Options → Save.
- **ffmpeg missing** → install per §2, restart terminal + companion. `/health` shows `ffmpeg:false` until fixed.
- **Age-restricted / private** → yt-dlp can't fetch anonymously; expected error, not a bug.
- **No Download button on YouTube** → YouTube SPA: wait 2s / navigate again; button injects next to Like/Share via `yt-navigate-finish` + MutationObserver.
- **1080p+ tiny file / no audio** → ffmpeg merge failed; check ffmpeg on PATH.
- **Port in use** → edit `companion/config.json` (`port`), restart, update extension Options URL to match.
