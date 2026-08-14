"""Stage 1 — URL validation (FR-002) and download via yt-dlp (FR-003)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yt_dlp

# Trailing video-title noise like "(Official Video)", "[4K Remaster]", "(Lyrics)".
# Conservative on purpose: only bracketed groups containing one of these words —
# the user can still fix anything at the confirm pause (FR-015).
_NOISE = re.compile(
    r"\s*[(\[][^)\]]*\b(official|video|audio|lyric|lyrics|visuali[sz]er|"
    r"remaster|remastered|hd|4k|mv|m/v)\b[^)\]]*[)\]]\s*$",
    re.IGNORECASE,
)


def clean_title(title: str, artist: str) -> str:
    """Best-effort song title from a video title (improves lookup hit rate)."""
    t = title.strip()
    while m := _NOISE.search(t):
        t = t[: m.start()].rstrip()
    if artist and t.lower().startswith(f"{artist.lower()} - "):
        t = t[len(artist) + 3 :].lstrip()
    return t or title.strip()


# YouTube video ids are 11 chars; accept a little slack rather than chase spec.
_MIN_VIDEO_ID = 8
_YT_VIDEO_PATHS = ("/shorts/", "/live/", "/embed/")


def validate_url(url: str) -> str | None:
    """Readable rejection reason for a non-YouTube/malformed URL, else None.

    Runs before any directory or network work, so a rejected URL creates no
    files (FR-002 acceptance). Playlist-only URLs are rejected — one video at
    a time (PRD §4 non-goal).
    """
    url = url.strip()
    try:
        parts = urlparse(url)
    except ValueError:
        return "that doesn't look like a valid URL."
    if parts.scheme not in ("http", "https"):
        return (
            "enter a full URL starting with https:// "
            "(e.g. https://www.youtube.com/watch?v=…)."
        )
    host = (parts.hostname or "").lower()
    if host == "youtu.be":
        if len(parts.path.strip("/").split("/")[0]) >= _MIN_VIDEO_ID:
            return None
        return "that youtu.be link is missing its video id."
    if host in ("youtube.com", "youtube-nocookie.com") or host.endswith(
        (".youtube.com", ".youtube-nocookie.com")
    ):
        path = parts.path
        if path.startswith("/watch"):
            video_id = parse_qs(parts.query).get("v", [""])[0]
            if len(video_id) >= _MIN_VIDEO_ID:
                return None
            return "that YouTube watch URL is missing its v= video id."
        for prefix in _YT_VIDEO_PATHS:
            if path.startswith(prefix) and len(path[len(prefix):].split("/")[0]) >= _MIN_VIDEO_ID:
                return None
        return (
            "that YouTube link isn't a single video "
            "(expected a watch, shorts, live, or youtu.be URL)."
        )
    return "only YouTube URLs are supported (youtube.com or youtu.be)."


@dataclass
class DownloadResult:
    audio_path: Path
    title: str
    artist: str
    duration: float  # seconds


def download_video(url: str, work_dir: Path) -> Path:
    """Download the video-only stream (≤1080p, MP4/h264 preferred) — M5.

    Feeds the optional video+lyrics-panel render: the audio track comes from
    the pipeline's MP3, so the video stream alone is enough. 1080p is already
    oversampled for the ~1440×810 layout slot; MP4/h264 decodes fastest in
    Remotion's ffmpeg-backed OffthreadVideo. Callers must treat failures as
    non-fatal (FR-011 spirit): the run continues with MP3 + lyrics.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bestvideo[height<=1080][ext=mp4]/bestvideo[height<=1080]/bestvideo",
        "outtmpl": str(work_dir / "source_video.%(ext)s"),
        "windowsfilenames": True,
        "noplaylist": True,  # one URL at a time (PRD §4 non-goal: no playlists)
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:
            raise RuntimeError("yt-dlp returned no video info for this URL")
        video_path = Path(ydl.prepare_filename(info))
    if not video_path.exists():
        raise RuntimeError(f"yt-dlp reported success but {video_path} is missing")
    return video_path


def download_audio(url: str, work_dir: Path) -> DownloadResult:
    """Download the best audio stream and capture title/artist/duration.

    Title/artist are best guesses — the user confirms or corrects them at the
    mandatory metadata pause (FR-015) before they are used for anything.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(work_dir / "source.%(ext)s"),
        "windowsfilenames": True,
        "noplaylist": True,  # one URL at a time (PRD §4 non-goal: no playlists)
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:
            raise RuntimeError("yt-dlp returned no video info for this URL")
        audio_path = Path(ydl.prepare_filename(info))

    # YouTube Music uploads carry real song metadata in track/artist; ordinary
    # videos only have title/uploader ("<channel> - Topic" for auto-channels).
    artist = (info.get("artist") or info.get("uploader") or "").strip()
    artist = artist.removesuffix(" - Topic").strip()
    # YouTube Music's `track` is authoritative; plain video titles get cleaned.
    title = (info.get("track") or "").strip() or clean_title(
        (info.get("title") or "").strip(), artist
    )
    duration = float(info.get("duration") or 0.0)

    if not audio_path.exists():
        raise RuntimeError(f"yt-dlp reported success but {audio_path} is missing")
    return DownloadResult(audio_path=audio_path, title=title, artist=artist, duration=duration)
