# YT Local Downloader

Download YouTube videos to your computer in high quality (up to 4K + MP3 audio).

It has two parts:

- **`extension/`** – a browser add-on (Chrome, Edge, Brave, Firefox). This is what you click.
- **`companion/`** – a small program that runs on your computer and does the actual downloading.

> **Please read:** this is for personal use only. Only download videos you own, or that are free to download (Creative Commons, public domain, or you have permission). You are responsible for following YouTube's rules and copyright law. Do not publish this add-on to the Chrome Web Store (their rules forbid it).

## What you need

- **Python 3.10 or newer** ([python.org](https://www.python.org), tick "Add to PATH" on Windows)
- **ffmpeg** (merges video + audio together)
- **Chrome, Edge, or Brave** (Firefox also works)

| System | Install command |
|---|---|
| Windows | `winget install Python.Python.3.12`, then `winget install Gyan.FFmpeg` |
| Mac | `brew install python ffmpeg` |
| Ubuntu / Debian | `sudo apt install python3 python3-venv ffmpeg` |
| Fedora | `sudo dnf install python3 ffmpeg` |

Check with: `python --version` and `ffmpeg -version`.

## Setup (one time, ~5 minutes)

**Step 1 — Start the downloader program.**

Windows: double-click `companion\run.bat`.

Mac / Linux:
```bash
cd companion
chmod +x run.sh
./run.sh
```

Leave that window open. On the first start it prints a line like this — copy the code:

```
[companion] API token: XaELW8MM9Au6wPJ6USiDpjH8GiYfgP7VZ5iYbJcbtA
```

That code is the password between the add-on and the program. Each computer makes its own.

**Step 2 — Add the extension to your browser.**

- Chrome / Edge / Brave: open `chrome://extensions` → turn on **Developer mode** → **Load unpacked** → pick the `extension` folder.
- Firefox: open `about:debugging` → **Load Temporary Add-on** → pick `extension/manifest.json`.

**Step 3 — Connect them.**

Right-click the extension icon → **Options**, then:

1. Server: `http://127.0.0.1:8765` (already filled in)
2. Paste the API token from Step 1
3. **Save** → **Test connection** (should turn green)

Done. You never need to do these steps again.

## Downloading videos

**On Windows:**

1. Double-click `companion\run.bat` and leave the window open.
2. Open any YouTube video.
3. Click the **Download** button next to Like/Share (or click the extension icon).
4. Pick a quality (e.g. 1080p, MP4) → **Download**.
5. The file appears in `Downloads\YTDownloader`. Close the window when finished.

**On Linux / Mac:**

1. Run `./run.sh` from the `companion` folder and leave it running.
2. Same as above: open a video → **Download** → pick quality → **Download**.
3. Files land in `~/Downloads/YTDownloader/`. Press `Ctrl+C` when finished.

**Tips:**

- Opened a playlist link? Choose **this video only** or the **whole playlist** (it queues every video with its own progress bar).
- Want just sound? Tick **Audio-only** and pick MP3 or M4A.
- Closing the popup mid-download is fine — progress keeps going and a notification pops up when it's done.
- The **History** tab lists everything: download again, open the folder, or delete.

## If something goes wrong

| Problem | Fix |
|---|---|
| "Cannot reach companion" | The `run.bat` / `run.sh` window is closed — start it again |
| "Invalid token" | Copy the token from the companion window into Options → Save (no extra spaces) |
| "Video unavailable" | The video is private, deleted, or members-only — nothing to fix |
| No Download button on the page | Wait a few seconds or reload — YouTube loads pages dynamically |
| File has no sound / tiny file | ffmpeg is missing — install it and restart the companion |

## For developers

Folder layout:

```
extension/   popup, options page, page button, background worker, icons
companion/   app (FastAPI server), requirements.txt, run scripts
```

The add-on talks to `http://127.0.0.1:8765` only. All endpoints except `/health` need the token (`Authorization: Bearer <token>`). Main endpoints: `/info` (video details), `/download` (start), `/progress/{id}` (live progress), `/cancel/{id}`, `/history`, `/settings`, `/update-ytdlp`.

Update yt-dlp from the Options page (**Update yt-dlp** button) or with `python -m pip install -U yt-dlp` inside the companion's `.venv`.
