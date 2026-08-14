"""Stage 6 — write the four lyric formats (FR-007; exact specs in PRD §7).

Line-level end times are derived from the next line's start; the last line
ends at track end.
"""

from __future__ import annotations

import json
from pathlib import Path

from .lyrics import LyricLine

# When track duration is unknown (0) the last line still needs an end time;
# give it a small fixed tail rather than a zero-length span.
_FALLBACK_TAIL_S = 3.0


def derive_end_times(lines: list[LyricLine], track_end: float) -> list[tuple[float, float, str]]:
    timed: list[tuple[float, float, str]] = []
    for i, ln in enumerate(lines):
        if i + 1 < len(lines):
            end = lines[i + 1].start
        else:
            end = track_end if track_end > ln.start else ln.start + _FALLBACK_TAIL_S
        timed.append((ln.start, max(end, ln.start), ln.text))
    return timed


def _mmss(t: float) -> str:
    m, s = divmod(int(round(t)), 60)
    return f"{m:02d}:{s:02d}"


def _srt_ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _lrc_ts(t: float) -> str:
    cs = int(round(t * 100))
    m, rem = divmod(cs, 6000)
    s, cs = divmod(rem, 100)
    return f"{m:02d}:{s:02d}.{cs:02d}"


def write_all(
    lines: list[LyricLine], track_end: float, folder: Path, base: str
) -> dict[str, Path]:
    """Write `<folder>/<base>.txt/.srt/.lrc/.json`; returns {extension: path}."""
    timed = derive_end_times(lines, track_end)

    txt = "\n".join(f"[{_mmss(s)}] {text}" for s, _e, text in timed) + "\n"

    srt_blocks = [
        f"{i}\n{_srt_ts(s)} --> {_srt_ts(e)}\n{text}\n"
        for i, (s, e, text) in enumerate(timed, start=1)
    ]
    srt = "\n".join(srt_blocks)

    lrc = "\n".join(f"[{_lrc_ts(s)}]{text}" for s, _e, text in timed) + "\n"

    payload = [
        {"start": round(s, 3), "end": round(e, 3), "text": text} for s, e, text in timed
    ]
    js = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    folder.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for ext, content in (("txt", txt), ("srt", srt), ("lrc", lrc), ("json", js)):
        path = folder / f"{base}.{ext}"
        path.write_text(content, encoding="utf-8")
        paths[ext] = path
    return paths
