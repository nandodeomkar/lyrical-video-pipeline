# Lyrical Video Pipeline

A Streamlit-based desktop app for creating lyrical (lyrics) videos from YouTube songs. Automates the full workflow: download audio → transcribe lyrics → correct → render video with synced lyrics overlay.

## Pipeline

```
YouTube URL → Download (yt-dlp) → Transcode (FFmpeg → WAV)
→ Transcribe (Whisper) → Correct (manual UI) → Export (LRC/SRT/JSON)
→ Render Video (lyrics overlay on audio)
```

## Features

- **YouTube Download** — Paste a URL, downloads best quality audio via yt-dlp
- **Auto-Transcription** — Whisper-powered speech-to-text with word-level timestamps (tiny → large-v3 models)
- **Lyrics Correction UI** — Side-by-side editor with audio playback synced to lyrics for manual fixes
- **Multiple Export Formats** — LRC, SRT, plain text, and JSON
- **Video Rendering** — Lyrics overlaid on audio via Remotion or built-in Python renderer
- **Run Logging** — Tracks pipeline runs with metadata (song, model, timings)

## Tech Stack

- **Python** + **Streamlit** — Multi-page app UI
- **yt-dlp** — YouTube audio downloading
- **OpenAI Whisper** (`stable-ts` / `faster-whisper`) — Speech-to-text transcription
- **FFmpeg** — Audio transcoding and video rendering

## Project Structure

```
app.py                  # Main Streamlit app (multi-page)
pipeline/
├── download.py         # YouTube audio download
├── transcode.py        # FFmpeg audio conversion
├── transcribe.py       # Whisper transcription
├── transcribe_worker.py
├── lyrics.py           # Lyric parsing, line splitting, silence gating
├── correct.py          # Correction & diffing logic
├── formats.py          # Format conversion (LRC ↔ SRT ↔ JSON ↔ text)
├── outputs.py          # Output file management
├── video.py            # Video rendering
└── runlog.py           # Pipeline run tracking
scripts/                # Smoke tests & rendering scripts
tests/                  # Test suite (11 test files)
```

## Getting Started

### Prerequisites

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/) installed and on PATH
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) installed and on PATH

### Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Run

```bash
streamlit run app.py
```

Or use the included `Launch Lyrics Pipeline.bat` for a one-click start.
