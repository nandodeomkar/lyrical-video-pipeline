"""Stage 6 — per-song output folder, naming, and collision safety (FR-009, FR-012)."""

from __future__ import annotations

import glob as _glob
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_EXTS = ("mp3", "txt", "srt", "lrc", "json")


def sanitize_name(name: str) -> str:
    """Make a Windows-safe folder/file base name."""
    name = _INVALID.sub("", name)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    return name or "Untitled"


@dataclass
class OutputPlan:
    folder: Path
    base: str        # possibly versioned, e.g. "Title - Artist (2)"
    versioned: bool  # True → collision found; UI must warn (FR-012)


def plan_output(out_root: Path, title: str, artist: str) -> OutputPlan:
    """Pick the output folder and a base name that overwrites nothing.

    Folder is always `<out_root>/<Title - Artist>` (FR-009). If any output
    file with the base name already exists in it, version the base name —
    "Title - Artist (2)", "(3)", … — instead of overwriting (FR-012).
    """
    base = sanitize_name(f"{title} - {artist}")
    folder = out_root / base

    def taken(candidate: str) -> bool:
        # `.video.*` is the M5 source-video file; its extension varies, and a
        # leftover one must version the base like any other output (FR-012).
        return any((folder / f"{candidate}.{ext}").exists() for ext in _EXTS) or any(
            folder.glob(_glob.escape(f"{candidate}.video") + ".*")
        )

    candidate = base
    n = 1
    while folder.exists() and taken(candidate):
        n += 1
        candidate = f"{base} ({n})"
    return OutputPlan(folder=folder, base=candidate, versioned=candidate != base)


def place_mp3(plan: OutputPlan, mp3_work_path: Path) -> Path:
    """Move the transcoded MP3 from the work dir into the output folder."""
    plan.folder.mkdir(parents=True, exist_ok=True)
    dest = plan.folder / f"{plan.base}.mp3"
    shutil.move(str(mp3_work_path), str(dest))
    return dest


def place_video(plan: OutputPlan, video_work_path: Path) -> Path:
    """Move the source music video into the output folder (M5).

    Named `<base>.video.<ext>` — the `.video.` infix keeps the source clear of
    rendered `<base>*.mp4` outputs, and the shared base ties it to its run.
    """
    plan.folder.mkdir(parents=True, exist_ok=True)
    dest = plan.folder / f"{plan.base}.video{video_work_path.suffix}"
    shutil.move(str(video_work_path), str(dest))
    return dest
