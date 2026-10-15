# YT Local Downloader

Download YouTube videos to your computer in high quality (up to 4K, or audio-only as MP3/M4A) with a one-click button inside the browser.

![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Manifest](https://img.shields.io/badge/extension-Manifest%20V3-green)
![Use](https://img.shields.io/badge/use-personal%20%2F%20sideloaded-lightgrey)

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
  - [Windows](#-windows)
  - [Linux](#-linux)
  - [macOS](#-macos)
  - [Load the extension (all systems)](#load-the-extension-all-systems)
  - [Connect the extension to the companion](#connect-the-extension-to-the-companion)
- [Usage](#usage)
- [Troubleshooting](#troubleshooting)
- [Updating](#updating)
- [Security & Privacy](#security--privacy)
- [For Developers](#for-developers)
- [Legal Notice](#legal-notice)

---

## Overview

The project has two parts that work together:

| Part | Folder | What it does |
| ---- | ------ | ------------ |
| **Browser extension** | `extension/` | The interface you click (popup, options page, and a Download button on YouTube). |
| **Local companion** | `companion/` | A small Python server on your PC that does the real work using `yt-dlp` and `ffmpeg`. |

```
 ┌──────────────────┐   HTTP + token    ┌──────────────────────────┐
 │ Browser extension│ ───────────────▶  │ Companion (127.0.0.1)    │
 │  (UI)            │ ◀───────────────  │ FastAPI + yt-dlp + ffmpeg│
 └──────────────────┘     progress      └────────────┬─────────────┘
                                                     ▼
                                          ~/Downloads/YTDownloader
```

## Features

- Download button added directly on the YouTube video page (next to Like / Share)
- Quality selection up to **4K**, MP4 output
- **Audio-only** mode with MP3 or M4A
- **Playlist support**: download one video or queue the whole playlist, each with its own progress bar
- Live progress, plus a desktop notification when a download finishes (even if the popup is closed)
- **History tab**: re-download, open the folder, or delete
- Works on Chrome, Edge, Brave, and Firefox
- Runs fully on your machine, no third-party servers

## Installation

You need **Python 3.10+**, **ffmpeg** (merges video and audio, converts to MP3), and a supported browser (Chrome, Edge, Brave, or Firefox).

Setup is done once and takes about 5 minutes. Follow the section for your system, then continue with [Load the extension](#load-the-extension-all-systems).

---

### 🪟 Windows

#### 1. Install the prerequisites

Open **CMD** or **PowerShell** and run:

```cmd
winget install Python.Python.3.12
winget install Gyan.FFmpeg
```

> If you install Python from [python.org](https://www.python.org) instead, tick **"Add python.exe to PATH"** during setup.

Close the terminal and open a **new** one, then verify:

```cmd
python --version
ffmpeg -version
```

#### 2. Start the companion

Double-click:

```
companion\run.bat
```

Keep the window open. The first launch creates a virtual environment and installs dependencies, so the token can take a while to appear.

#### 3. Copy the token

When ready, the window prints:

```
[companion] API token: <your-unique-token>
```

Copy it. It is the password between the extension and the companion, and each computer generates its own.

#### 4. Where files are saved

```
Downloads\YTDownloader
```

To stop the companion, close the window.

---

### 🐧 Linux

#### 1. Install the prerequisites

**Ubuntu / Debian**

```bash
sudo apt update
sudo apt install python3 python3-venv ffmpeg
```

**Fedora**

```bash
sudo dnf install python3 ffmpeg
```

Verify:

```bash
python3 --version
ffmpeg -version
```

#### 2. Start the companion

```bash
cd companion
chmod +x run.sh
./run.sh
```

Keep the terminal open. The first launch creates a virtual environment and installs dependencies, so the token can take a while to appear.

#### 3. Copy the token

When ready, the terminal prints:

```
[companion] API token: <your-unique-token>
```

Copy it. It is the password between the extension and the companion, and each computer generates its own.

#### 4. Where files are saved

```
~/Downloads/YTDownloader/
```

To stop the companion, press `Ctrl+C`.

---

### 🍎 macOS

#### 1. Install the prerequisites

```bash
brew install python ffmpeg
```

Verify:

```bash
python3 --version
ffmpeg -version
```

#### 2. Start the companion

```bash
cd companion
chmod +x run.sh
./run.sh
```

Copy the `API token` line it prints, same as on Linux. Files are saved to `~/Downloads/YTDownloader/`. Press `Ctrl+C` to stop.

---

### Load the extension (all systems)

#### Chrome / Edge / Brave

1. Open `chrome://extensions` (or `edge://extensions`, `brave://extensions`)
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select the `extension` folder

#### Firefox

1. Open `about:debugging#/runtime/this-firefox`
2. Click **Load Temporary Add-on**
3. Select `extension/manifest.json`

> Firefox removes temporary add-ons when the browser closes, so you need to reload it each session.

### Connect the extension to the companion

Right-click the extension icon, choose **Options**, then:

1. **Server:** `http://127.0.0.1:8765` (already filled in)
2. **API token:** paste the token you copied
3. Click **Save**, then **Test connection**. It should turn green.

You never need to repeat these steps.

## Usage

1. Start the companion and leave it running:
   - **Windows:** double-click `companion\run.bat`
   - **Linux / macOS:** run `./run.sh` from the `companion` folder
2. Open any YouTube video.
3. Click the **Download** button below the video, or click the extension icon.
4. Choose a quality (e.g. 1080p MP4), or tick **Audio-only** and pick MP3 / M4A.
5. Click **Download**.

### Tips

- **Playlist links:** choose *this video only* or *the whole playlist*.
- **Closing the popup** mid-download is fine. Progress continues in the background.
- **History tab:** download again, open the containing folder, or delete entries.

## Troubleshooting

| Problem | Fix |
| ------- | --- |
| "Cannot reach companion" | The `run.bat` / `run.sh` window is closed. Start it again. |
| "Invalid token" | Copy the token from the companion window into **Options → Save**. Make sure there are no extra spaces. |
| "Video unavailable" | The video is private, deleted, age/region restricted, or members-only. |
| No Download button on the page | Wait a few seconds or reload the page. YouTube loads content dynamically. |
| Downloaded file has no sound, or is tiny | ffmpeg is missing. Install it and restart the companion. |
| Downloads suddenly start failing | YouTube changed something. [Update yt-dlp](#updating). |
| **Windows:** `python` is not recognized | Reinstall Python with *Add to PATH* ticked, or open a new terminal. |
| **Linux:** `venv` / `ensurepip` error | Install the venv package: `sudo apt install python3-venv`. |
| **Linux/macOS:** `Permission denied` on `run.sh` | Run `chmod +x run.sh` first. |

## Updating

`yt-dlp` needs frequent updates because YouTube changes often. Either:

- Click **Update yt-dlp** on the extension's Options page, or
- Run this inside the companion's virtual environment:

  ```bash
  python -m pip install -U yt-dlp
  ```

To update the project itself, pull the latest code and reload the extension from the extensions page.

## Security & Privacy

- The companion listens on `127.0.0.1` only, so it is not reachable from other devices on your network.
- Every endpoint except `/health` requires the token (`Authorization: Bearer <token>`).
- **Never share or commit your API token.** If it has been exposed, generate a new one.
- No data is sent to any server other than YouTube (via `yt-dlp`).

## For Developers

### Project layout

```
yt-local-downloader/
├── extension/    # popup, options page, page button, background worker, icons
├── companion/    # app (FastAPI server), requirements.txt, run scripts
├── .gitignore
└── README.md
```

### API

Base URL: `http://127.0.0.1:8765`. All endpoints except `/health` require `Authorization: Bearer <token>`.

| Endpoint | Purpose |
| -------- | ------- |
| `/health` | Liveness check (no token needed) |
| `/info` | Fetch video details |
| `/download` | Start a download |
| `/progress/{id}` | Live progress of a download |
| `/cancel/{id}` | Cancel a download |
| `/history` | List past downloads |
| `/settings` | Read / change settings |
| `/update-ytdlp` | Update yt-dlp |

## Legal Notice

This tool is intended for **personal use only**. Download only videos that you own, or that are free to download (Creative Commons, public domain, or with the owner's permission). You are responsible for complying with YouTube's Terms of Service and applicable copyright law.

Do not publish this extension to the Chrome Web Store, as its policies do not allow it. It is meant to be sideloaded.
