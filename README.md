<div align="center">

# 🎬 Google Drive Video Extractor — CDP

**Download Google Drive videos at any quality with full automation**

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-blue?logo=windows)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Chrome](https://img.shields.io/badge/Requires-Google%20Chrome-yellow?logo=googlechrome)](https://www.google.com/chrome/)

</div>

---

## What is this?

**Google Drive Video Extractor - CDP** is a tool that downloads videos from Google Drive by hooking into the browser's own network traffic using the **Chrome DevTools Protocol (CDP)**.

Instead of trying to guess video URLs or use unofficial APIs, the tool opens a real Chrome session, lets the browser authenticate and play the video normally, then intercepts the direct video/audio stream URLs at the network level and downloads them in full quality.

The final output is a merged `.mp4` file (video + audio combined) saved to your machine.

---

## How it works

```
User provides URL
       ↓
Tool clones Chrome profile (It will not copy login/cookies or saved history. You must log back into your Google Drive account.)
       ↓
Launches Chrome with remote debugging enabled (port 9222)
       ↓
Connects via CDP WebSocket and monitors all network requests
       ↓
Auto-plays the video to trigger stream requests
       ↓
Intercepts video + audio stream URLs
       ↓
Applies your quality preference
       ↓
Downloads video + audio in parallel chunks
       ↓
Merges with ffmpeg → final .mp4 file
```

---

## Features

- **Single URL mode** — paste one link and download
- **Batch / Auto mode** — process a list of URLs automatically from `list-url.txt`
- **Quality selection** — choose from 144p up to 2160p (4K), or let the tool pick the best available
- **Auto-play & detect** — automatically triggers video playback to capture stream URLs
- **Profile cloning** — uses your existing Chrome profile without touching your original browser profile (It will not copy login/cookies or saved history. You must log back into your Google Drive account.)
- **Crash reports** — detailed error logs saved locally on failure
- **Organized output** — each run gets its own timestamped folder inside `output/`
---

## Requirements

### Common (both modes)

| Requirement | Details |
|---|---|
| **OS** | Windows 10 / 11 (64-bit) |
| **Google Chrome** | Any recent version, must be installed |
| **ffmpeg + ffprobe** | Must be placed in `tools/` folder |
| **Google account** | Must be logged in to Chrome and have access to the video if needed|

### Python mode only

| Requirement | Version |
|---|---|
| Python | 3.8 or higher |
| aiohttp | `pip install aiohttp` |

### EXE build mode only

| Requirement | Details |
|---|---|
| Python | 3.8+ (for building only) |
| Nuitka | `pip install nuitka` |
| aiohttp | `pip install aiohttp` |

---

## Getting ffmpeg

Download a **static build** for Windows (no extra DLLs needed):

➡️ **https://www.gyan.dev/ffmpeg/builds/**

Download `ffmpeg-release-essentials.7z`, extract it, then copy `ffmpeg.exe` and `ffprobe.exe` to the `tools/` folder.

---

## Repository structure

```
📁 Repository
├── 📄 Google drive CDP v* by DEVTE.py   ← Run directly with Python
├── 📁 build exe
    ├── 📄 cdp_extractor.py                       ← EXE build: main app source
    ├── 📄 launcher.py                            ← EXE build: launcher source
    ├── 📄 build.bat                              ← EXE build: build script, run this to make exe
└──
```

---

## Usage — Python (direct)

No build step needed. Just install the dependency and run:

```bash
pip install aiohttp
python "Google drive CDP v* by DEVTE.py"
```

**What you will see:**

```
Select Mode
  1  ─  Single URL
  2  ─  Batch / Auto  (uses list-url.txt)
  3  ─  Exit
```

---

## Usage — EXE Build

### 1. Build

```bat
pip install nuitka aiohttp
build.bat
```

Build time: approximately 5–10 minutes.

### 2. Output structure after build

```
dist/
├── Launcher.exe           ← Run this
├── tools/                 ← Put ffmpeg.exe + ffprobe.exe here
├── output/                ← Downloaded videos appear here
├── logs/                  ← Log files
├── temp/                  ← Chrome profile clone (auto-managed)
└── AppCore/
    ├── CDP-v*.exe     ← do not run directly
    └── [Nuitka runtime]
```

### 3. Run

Double-click `Launcher.exe` or run it from a terminal.

> ⚠️ **Do not run `AppCore\CDP-v*.exe` directly.**
> It will refuse to start without the Launcher.

---

## Batch mode

Create a file called `list-url.txt` in the same folder as the program.
Add one Google Drive video URL per line:

```
https://drive.google.com/file/d/XXXXXXXXXX/view
https://drive.google.com/file/d/YYYYYYYYYY/view
```

Run the program and select **Mode 2 — Batch / Auto**.

Results are saved to `output/` and processed URLs are moved to `list-done.txt`.
Failed URLs are recorded in `list-error.txt`.

---

## Quality options

| Option | Behavior |
|---|---|
| `Max` | Highest available quality |
| `2160p` | 4K (if available) |
| `1440p` | 2K |
| `1080p` | Full HD |
| `720p` | HD |
| `480p` | SD |
| `360p` | Low |
| `240p` | Very low |
| `144p` | Minimum |

If the requested quality is not available, the tool automatically falls back to the nearest lower quality.

---

## Notes
- The cloned Chrome profile is stored in `temp/chrome_clone/` and is reused between runs to avoid repeated profile copying.
- All activity is logged to `logs/` for debugging purposes.
- `ffmpeg` and `ffprobe` must be the **static build** variants to avoid DLL dependency issues.

---

<div align="center">
Made by <strong>DEVTE</strong>
</div>
