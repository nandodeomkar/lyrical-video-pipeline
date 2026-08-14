"""Stage 2 — transcode the downloaded audio to a 320 kbps MP3 via ffmpeg (FR-004)."""

from __future__ import annotations

import subprocess
from pathlib import Path


def transcode_to_mp3(source: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",  # dest lives in the per-run work dir; output-folder safety is FR-012's job
        "-i", str(source),
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", "320k",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not dest.exists():
        raise RuntimeError(
            f"ffmpeg failed (exit {proc.returncode}):\n{(proc.stderr or '')[-2000:]}"
        )
    return dest
