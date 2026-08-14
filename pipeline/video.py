"""Lyric-video rendering via Remotion (M4/M5 — user-approved scope extensions).

Renders `<song folder>/<base>.mp4` (lyrics-only, M4) or
`<base> [video+lyrics].mp4` (music video + lyrics panel, M5) from the folder's
MP3 + `.json` lyrics — the panel layout additionally needs the
`<base>.video.*` source video, fetchable on demand via `fetch_video`.
Per-song data goes in as Remotion input props (`--props=<file>`); the song
folder itself becomes the Remotion public dir so the MP3 and video play
without copying into the project.

The `video/node_modules` directory is a junction into the vendored install at
`..\\Video Production\\vendor\\remotion\\node_modules` — machine setup, not a
pip dependency. The CLI is invoked through `node` directly (`.cmd` shims need
a shell on Windows), always with explicit arguments: a bare `remotion render`
starts rendering defaults instead of printing help.
"""

from __future__ import annotations

import colorsys
import glob as _glob
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import deque
from pathlib import Path
from typing import Callable, Literal

from pipeline.download import download_video
from pipeline.outputs import sanitize_name

ROOT = Path(__file__).resolve().parent.parent
VIDEO_PROJECT = ROOT / "video"
LOG_DIR = ROOT / "logs"
_CLI_JS = VIDEO_PROJECT / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
COMPOSITION = "LyricVideo"
# Render-load guardrails (2026-06-11, user request — panel renders froze the
# laptop). The render may use the AMD GPU: Q-003's CPU-only decision covers
# transcription (WhisperX/CTranslate2 are CUDA-only), not Chrome compositing,
# which ANGLE maps onto D3D11/Radeon. GPU needs Chrome for Testing — the
# default headless shell ignores the GPU; Remotion downloads it on first use.
GPU_DEFAULT = True
CONCURRENCY_DEFAULT = 4  # half the 4800H's physical cores — keeps the UI alive
_OFFTHREAD_CACHE_BYTES = 2 * 1024**3  # cap frame-extraction RAM (16 GB machine)

# M6: per-song colorwash palette. Mirrors DEFAULT_PALETTE in video/src/theme.tsx.
DEFAULT_PALETTE = ["#472768", "#263954", "#2c2673"]
_SAMPLE_POSITIONS = (0.10, 0.30, 0.50, 0.70, 0.90)
_MIN_HUE_DISTANCE = 0.08  # circular hue distance below which two colors merge
_MAX_PALETTE_COLORS = 3
_FFMPEG_TIMEOUT = 30  # seconds per probe/sample — extraction is best-effort
# M5: each layout maps to a composition and a distinguishable output base.
LAYOUTS: dict[str, tuple[str, str]] = {
    "lyrics": ("LyricVideo", ""),
    "panel": ("VideoPanel", " [video+lyrics]"),
}

_VERSION_SUFFIX = re.compile(r"\s*\(\d+\)$")


class VideoSetupError(RuntimeError):
    """The Remotion project or its vendored node_modules is unavailable."""


def find_song_files(folder: Path) -> tuple[str, Path, Path]:
    """Newest `(base, mp3, json)` set in a song folder.

    Versioned runs leave several bases ("Title - Artist", "… (2)"); the most
    recently modified lyrics `.json` with a matching MP3 wins.
    """
    by_newest = sorted(
        folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for json_path in by_newest:
        mp3 = json_path.with_suffix(".mp3")
        if mp3.exists():
            return json_path.stem, mp3, json_path
    raise FileNotFoundError(f"no MP3 + .json lyrics pair found in {folder}")


def find_video_file(folder: Path, base: str) -> Path:
    """Newest `<base>.video.*` source video in a song folder (M5).

    Raises FileNotFoundError when the song was processed before video download
    existed (or its stage-1 download failed) — callers offer `fetch_video`.
    """
    matches = sorted(
        folder.glob(_glob.escape(f"{base}.video") + ".*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not matches:
        raise FileNotFoundError(
            f'no "{base}.video.*" source video in {folder} — re-run the song '
            "through the app (stage 1 now downloads it) or fetch it on demand."
        )
    return matches[0]


def find_run_url(log_dir: Path, base: str) -> str | None:
    """Newest successful run URL for this song from `logs/runs.jsonl` (M5).

    Matched by comparing the sanitized "Title - Artist" of each record against
    the version-stripped folder base, so log titles with characters that were
    stripped from the folder name still match.
    """
    log = log_dir / "runs.jsonl"
    if not log.exists():
        return None
    target = _VERSION_SUFFIX.sub("", base).strip().casefold()
    url: str | None = None
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue  # a malformed line must never block a render
        if not rec.get("success") or not rec.get("url"):
            continue
        rec_base = sanitize_name(f"{rec.get('title', '')} - {rec.get('artist', '')}")
        if rec_base.casefold() == target:
            url = rec["url"]  # keep scanning: the last match is the newest
    return url


def fetch_video(song_dir: Path, log_dir: Path | None = None) -> Path:
    """Get the song's source video, downloading it on demand if missing (M5).

    Rescues folders processed before stage 1 downloaded videos: the YouTube
    URL is recovered from the run log. Returns the `<base>.video.<ext>` path.
    """
    song_dir = Path(song_dir).resolve()
    base, _, _ = find_song_files(song_dir)
    try:
        return find_video_file(song_dir, base)
    except FileNotFoundError:
        pass
    url = find_run_url(log_dir or LOG_DIR, base)
    if not url:
        title, artist = parse_base(base)
        raise RuntimeError(
            f'no YouTube URL found in the run log for "{title} - {artist}" — '
            "re-run the song once through the app to fetch its video."
        )
    with tempfile.TemporaryDirectory(prefix="fetchvideo-") as tmp:
        work_video = download_video(url, Path(tmp))
        dest = song_dir / f"{base}.video{work_video.suffix}"
        shutil.move(str(work_video), str(dest))
    return dest


def parse_base(base: str) -> tuple[str, str]:
    """'Title - Artist (2)' → ('Title', 'Artist') per the FR-009 naming."""
    base = _VERSION_SUFFIX.sub("", base).strip()
    if " - " in base:
        title, artist = base.rsplit(" - ", 1)
        return title.strip(), artist.strip()
    return base, ""


def _tune_color(rgb: tuple[int, int, int]) -> str:
    """Clamp a sampled color into the dark, text-safe wash band (M6).

    Lightness is clamped so white lyrics stay readable on the wash; the
    saturation floor keeps near-gray frames from going muddy.
    """
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    l = min(max(l, 0.16), 0.34)
    s = max(s, 0.35)
    r, g, b = (round(c * 255) for c in colorsys.hls_to_rgb(h, l, s))
    return f"#{r:02x}{g:02x}{b:02x}"


def _probe_duration(video_path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video_path)],
        capture_output=True,
        text=True,
        timeout=_FFMPEG_TIMEOUT,
    )
    return float(out.stdout.strip())


def _sample_rgb(video_path: Path, seconds: float) -> tuple[int, int, int] | None:
    """Average frame color at `seconds`: one frame scaled to 1×1 px raw rgb24."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{seconds:.3f}", "-i", str(video_path),
         "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
        timeout=_FFMPEG_TIMEOUT,
    )
    data = out.stdout
    if out.returncode != 0 or len(data) < 3:
        return None
    return data[0], data[1], data[2]


def extract_palette(video_path: Path) -> list[str] | None:
    """2–3 tuned wash colors sampled from the source video, or None (M6).

    Best-effort by contract: any failure (no ffmpeg/ffprobe, odd codec, junk
    file) returns None and the caller falls back to DEFAULT_PALETTE —
    extraction must never break a render.
    """
    try:
        duration = _probe_duration(video_path)
        if duration <= 0:
            return None
        colors: list[str] = []
        hues: list[float] = []
        for pos in _SAMPLE_POSITIONS:
            rgb = _sample_rgb(video_path, duration * pos)
            if rgb is None:
                continue
            h, _, _ = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
            if any(min(abs(h - p), 1 - abs(h - p)) < _MIN_HUE_DISTANCE for p in hues):
                continue  # near-duplicate hue — the wash wants distinct colors
            hues.append(h)
            colors.append(_tune_color(rgb))
            if len(colors) == _MAX_PALETTE_COLORS:
                break
        return colors or None
    except Exception:
        return None


def _props_for(
    json_path: Path,
    title: str,
    artist: str,
    audio_name: str,
    palette: list[str] | None = None,
) -> dict:
    lines = json.loads(json_path.read_text(encoding="utf-8"))
    if not lines:
        raise ValueError(f"{json_path.name} contains no lyric lines")
    return {
        "title": title,
        "artist": artist,
        # By the formats convention the last line ends at track end.
        "duration": float(lines[-1]["end"]),
        "audioFile": audio_name,
        "lines": lines,
        "palette": list(palette) if palette else list(DEFAULT_PALETTE),
    }


def _versioned_mp4(folder: Path, base: str) -> Path:
    """Never overwrite an existing render (FR-012 spirit)."""
    candidate = folder / f"{base}.mp4"
    n = 2
    while candidate.exists():
        candidate = folder / f"{base} ({n}).mp4"
        n += 1
    return candidate


def _build_command(
    out_mp4: Path,
    props_file: Path,
    public_dir: Path,
    frames: str | None,
    composition: str = COMPOSITION,
    *,
    gpu: bool = GPU_DEFAULT,
    concurrency: int = CONCURRENCY_DEFAULT,
) -> list[str]:
    cmd = [
        "node",
        str(_CLI_JS),
        "render",
        "src/index.ts",
        composition,
        str(out_mp4),
        f"--props={props_file}",
        f"--public-dir={public_dir}",
        f"--concurrency={concurrency}",
        f"--offthreadvideo-cache-size-in-bytes={_OFFTHREAD_CACHE_BYTES}",
    ]
    if gpu:
        cmd += ["--gl=angle", "--chrome-mode=chrome-for-testing"]
    if frames:
        cmd.append(f"--frames={frames}")
    return cmd


def render_lyric_video(
    song_dir: Path,
    *,
    layout: Literal["lyrics", "panel"] = "lyrics",
    title: str | None = None,
    artist: str | None = None,
    on_progress: Callable[[str], None] | None = None,
    frames: str | None = None,
    out_path: Path | None = None,
    gpu: bool = GPU_DEFAULT,
    concurrency: int = CONCURRENCY_DEFAULT,
) -> Path:
    """Render the song folder's lyric video; returns the written MP4 path.

    `layout="panel"` (M5) renders the music video + lyrics-panel composition
    instead — it needs the folder's `<base>.video.*` source file and writes
    `<base> [video+lyrics].mp4`. `frames` ("0-120") renders a clip — used by
    the smoke test. `out_path` overrides the default versioned destination.
    `gpu=False` falls back to the software rasterizer (headless shell).
    """
    # The CLI subprocess runs with cwd=video/, so relative caller paths would
    # silently resolve against the project dir — Remotion treats a missing
    # public dir as empty and the audio 404s mid-render. Absolute, always.
    song_dir = Path(song_dir).resolve()
    composition, out_suffix = LAYOUTS[layout]
    if not _CLI_JS.exists():
        raise VideoSetupError(
            f"Remotion CLI not found at {_CLI_JS} — video/node_modules must be a "
            'junction to "Video Production\\vendor\\remotion\\node_modules".'
        )
    base, mp3, json_path = find_song_files(song_dir)
    guessed_title, guessed_artist = parse_base(base)
    if layout == "panel":
        source_video: Path | None = find_video_file(song_dir, base)
    else:
        try:
            source_video = find_video_file(song_dir, base)  # for color only (M6)
        except FileNotFoundError:
            source_video = None
    palette = (extract_palette(source_video) if source_video else None) or DEFAULT_PALETTE
    props = _props_for(
        json_path, title or guessed_title, artist or guessed_artist, mp3.name, palette
    )
    if layout == "panel":
        assert source_video is not None
        props["videoFile"] = source_video.name
    out_mp4 = (
        Path(out_path).resolve() if out_path else _versioned_mp4(song_dir, base + out_suffix)
    )

    fd, tmp_name = tempfile.mkstemp(suffix=".json", prefix="lyricvideo-props-")
    props_file = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(props, f, ensure_ascii=False)
        tail: deque[str] = deque(maxlen=15)
        proc = subprocess.Popen(
            _build_command(
                out_mp4, props_file, song_dir, frames, composition,
                gpu=gpu, concurrency=concurrency,
            ),
            cwd=VIDEO_PROJECT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            # Windows children inherit the below-normal class, so node's Chrome
            # and ffmpeg workers do too — a saturated render can't freeze the UI.
            creationflags=getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0),
        )
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if line:
                tail.append(line)
                if on_progress:
                    on_progress(line)
        if proc.wait() != 0:
            raise RuntimeError("Remotion render failed:\n" + "\n".join(tail))
    finally:
        props_file.unlink(missing_ok=True)
    if not out_mp4.exists():
        raise RuntimeError(f"render reported success but {out_mp4} is missing")
    return out_mp4
